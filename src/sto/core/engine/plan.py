"""A canonical schedule as a network the forward pass can take.

This is where policy lives. :mod:`sto.core.engine.network` carries none, and
:mod:`sto.core.engine.forward` reads none: everything about *which* calendar an
activity works to, *which* calendar a lag is consumed on, and *which* rows are
scheduled at all is decided here, once, against the canonical model, and is
reported rather than assumed.

Two rules the previous engine got wrong by omission are answered explicitly.

An activity naming a calendar that is not in the file is **not** the same as an
activity naming none. The first is a broken reference and the second inherits
the project's default; the previous importer turned both into ``None`` and lost
the difference, which is recorded in ``docs/goals/ACTIVE.md`` as owed to this
slice. Here the broken reference excludes the activity with a code and the
inheriting one resolves.

Nothing is dropped silently. Every activity or relationship the plan will not
schedule appears in :attr:`Plan.excluded` with a code saying why, so a shrinking
cohort is visible rather than looking like a clean run over fewer rows.

The forward pass works in whatever unit the calendars were compiled in --
integer seconds from a shared epoch, here -- so :meth:`Plan.to_datetime` is how
a coordinate becomes a wall-clock moment again. The epoch is shared across every
calendar in the plan, because coordinates from two epochs cannot be compared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sto.core.calendar.arithmetic import CompiledIntervals, intersect_intervals
from sto.core.calendar.compile import CompiledCalendar, Horizon, compile_calendars
from sto.core.model.entities import Activity, Schedule
from sto.core.model.enums import (
    ActivityKind,
    ConstraintType,
    LagCalendar,
    MilestoneSnapPolicy,
)

from .network import Network, PlannedActivity, PlannedRelationship

#: Kinds the forward pass schedules. A summary is a rollup of its children (S6),
#: and level-of-effort and hammock activities take their span from other rows
#: rather than from their own duration, so none of the three is scheduled here.
SCHEDULED_KINDS = frozenset(
    {ActivityKind.TASK, ActivityKind.START_MILESTONE, ActivityKind.FINISH_MILESTONE}
)

#: Constraint types that need a date to mean anything.
_DATED = frozenset(
    {
        ConstraintType.SNET,
        ConstraintType.SNLT,
        ConstraintType.FNET,
        ConstraintType.FNLT,
        ConstraintType.MSO,
        ConstraintType.MFO,
    }
)


@dataclass(frozen=True, slots=True)
class Excluded:
    """A row the plan will not schedule, and the code that says why."""

    uid: UUID
    kind: str
    code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Plan:
    """A network, the calendars behind it, and everything left out of it."""

    network: Network
    epoch: datetime
    calendars: dict[UUID, CompiledCalendar]
    excluded: tuple[Excluded, ...] = ()
    snap_milestones: bool = False

    def to_datetime(self, coordinate: int) -> datetime:
        return self.epoch + timedelta(seconds=coordinate)

    def to_seconds(self, moment: datetime) -> int:
        return int((moment - self.epoch).total_seconds())

    def excluded_by_code(self) -> dict[str, int]:
        """How many rows each code accounts for -- the shape of a shrinking cohort."""

        counts: dict[str, int] = {}
        for row in self.excluded:
            counts[row.code] = counts.get(row.code, 0) + 1
        return counts


def _duration_seconds(activity: Activity) -> int:
    if activity.planned_duration is None:
        return 0
    return activity.planned_duration.seconds


def build_plan(
    schedule: Schedule,
    horizon: Horizon,
    *,
    epoch: datetime | None = None,
    resource_calendars_apply: bool = False,
) -> Plan:
    """Compile the calendars once, then map every row onto them.

    ``resource_calendars_apply`` intersects an activity's calendar with its
    assigned resource's. The reference semantics do this -- the corpus has a
    case for it -- but on the BOILER schedule it is measurably wrong: sixteen
    activities carry a single resource whose calendar is disjoint from the task
    calendar, and intersecting leaves them with no working time at all and
    therefore unschedulable. Microsoft Project has a task-level
    ``IgnoreResourceCalendar`` flag and its own rule for which calendar wins,
    and neither is measured here, so this defaults to off on a Microsoft file
    and the question is left named rather than answered wrongly.
    """

    calendars = compile_calendars(schedule, horizon, epoch=epoch)
    if not calendars:
        raise ValueError("the schedule carries no calendars to compile")
    any_calendar = next(iter(calendars.values()))
    shared_epoch = any_calendar.epoch
    window = any_calendar.horizon
    continuous = CompiledIntervals.of((window,))

    project = schedule.project
    excluded: list[Excluded] = []

    resources = {resource.uid: resource for resource in schedule.resources}
    assignments_by_activity: dict[UUID, list[UUID]] = {}
    for assignment in schedule.assignments:
        if assignment.activity_uid is None or assignment.resource_uid is None:
            continue
        assignments_by_activity.setdefault(assignment.activity_uid, []).append(
            assignment.resource_uid
        )

    def to_seconds(moment: datetime) -> int:
        return int((moment - shared_epoch).total_seconds())

    def effective_calendar(
        activity: Activity,
    ) -> tuple[CompiledIntervals | None, str, str]:
        """The activity's calendar intersected with its resource's.

        Returns the calendar with an empty code, or ``None`` with the code and
        detail saying why: the activity named a calendar the file does not
        carry, the activity named none and the project has no default to
        inherit, a resource named a calendar that is not there, or the activity
        carries resources on more than one calendar.
        """

        unresolved = "ACTIVITY_CALENDAR_UNRESOLVED"
        if activity.calendar_uid is not None:
            compiled = calendars.get(activity.calendar_uid)
            if compiled is None:
                return (
                    None,
                    unresolved,
                    f"activity calendar {activity.calendar_uid} is not in the file",
                )
            intervals = compiled.intervals.intervals
        elif project.default_calendar_uid is not None:
            compiled = calendars.get(project.default_calendar_uid)
            if compiled is None:
                return None, unresolved, "the project default calendar is not in the file"
            intervals = compiled.intervals.intervals
        else:
            return (
                None,
                unresolved,
                "the activity names no calendar and the project has no default",
            )

        if not resource_calendars_apply:
            return CompiledIntervals.of(intervals), "", ""

        # Resource calendars: intersect one, refuse several. Two shift calendars
        # are routinely disjoint, so intersecting them annihilates the working
        # time and the activity silently becomes unschedulable. See
        # ``resource_calendars_apply`` on :func:`build_plan` for why this is off
        # by default on a Microsoft file.
        resource_calendars = {
            resources[uid].calendar_uid
            for uid in assignments_by_activity.get(activity.uid, [])
            if uid in resources and resources[uid].calendar_uid is not None
        }
        if len(resource_calendars) > 1:
            return (
                None,
                "ACTIVITY_MULTIPLE_RESOURCE_CALENDARS",
                f"{len(resource_calendars)} distinct resource calendars",
            )
        for calendar_uid in resource_calendars:
            resource_calendar = calendars.get(calendar_uid)
            if resource_calendar is None:
                return (
                    None,
                    "ACTIVITY_CALENDAR_UNRESOLVED",
                    f"resource calendar {calendar_uid} is not in the file",
                )
            intervals = intersect_intervals(intervals, resource_calendar.intervals.intervals)
        return CompiledIntervals.of(intervals), "", ""

    activities: list[PlannedActivity] = []
    scheduled: set[UUID] = set()
    for activity in schedule.activities:
        if activity.kind not in SCHEDULED_KINDS:
            excluded.append(
                Excluded(
                    activity.uid,
                    "activity",
                    "ACTIVITY_KIND_NOT_SCHEDULED",
                    activity.kind.value,
                )
            )
            continue
        if not activity.active:
            excluded.append(Excluded(activity.uid, "activity", "ACTIVITY_INACTIVE"))
            continue
        if activity.planned_duration is not None and activity.planned_duration.elapsed:
            # An elapsed duration is wall-clock, not working time, so it does not
            # belong on the activity's calendar. No real file here carries one.
            excluded.append(
                Excluded(activity.uid, "activity", "ACTIVITY_DURATION_ELAPSED")
            )
            continue

        calendar, code, detail = effective_calendar(activity)
        if calendar is None:
            excluded.append(Excluded(activity.uid, "activity", code, detail))
            continue
        if not calendar.intervals:
            excluded.append(Excluded(activity.uid, "activity", "ACTIVITY_CALENDAR_EMPTY"))
            continue

        constraint_type = ConstraintType.ASAP
        coordinate: int | None = None
        primary = activity.primary_constraint
        if primary is not None and primary.type is not ConstraintType.ASAP:
            if primary.type in _DATED:
                if primary.date is None:
                    excluded.append(
                        Excluded(
                            activity.uid,
                            "activity",
                            "ACTIVITY_CONSTRAINT_INCOMPLETE",
                            primary.type.value,
                        )
                    )
                    continue
                coordinate = to_seconds(primary.date)
            constraint_type = primary.type
        if activity.secondary_constraint is not None:
            excluded.append(
                Excluded(
                    activity.uid,
                    "activity",
                    "ACTIVITY_SECONDARY_CONSTRAINT_NOT_APPLIED",
                    activity.secondary_constraint.type.value,
                )
            )

        activities.append(
            PlannedActivity(
                uid=activity.uid,
                duration=_duration_seconds(activity),
                calendar=calendar,
                constraint_type=constraint_type,
                constraint_coordinate=coordinate,
            )
        )
        scheduled.add(activity.uid)

    activity_calendars = {row.uid: row.calendar for row in activities}
    relationships: list[PlannedRelationship] = []
    for relationship in schedule.relationships:
        if (
            relationship.predecessor_uid not in scheduled
            or relationship.successor_uid not in scheduled
        ):
            excluded.append(
                Excluded(relationship.uid, "relationship", "RELATIONSHIP_ENDPOINT_NOT_SCHEDULED")
            )
            continue

        lag = relationship.lag
        lag_seconds = 0 if lag is None else lag.seconds
        policy = relationship.lag_calendar
        if policy is LagCalendar.INHERIT_PROJECT_POLICY:
            policy = project.lag_calendar_policy
        if lag is not None and lag.elapsed:
            policy = LagCalendar.ELAPSED_24H

        lag_calendar: CompiledIntervals | None
        if lag_seconds == 0:
            # Zero lag never touches a calendar, so an unresolvable policy is
            # not a reason to drop the edge.
            lag_calendar = None
        elif policy is LagCalendar.ELAPSED_24H:
            lag_calendar = continuous
        elif policy is LagCalendar.SUCCESSOR:
            lag_calendar = None  # the engine's default is the successor's own
        elif policy is LagCalendar.PREDECESSOR:
            lag_calendar = activity_calendars[relationship.predecessor_uid]
        elif policy is LagCalendar.PROJECT:
            default = project.default_calendar_uid
            compiled = calendars.get(default) if default is not None else None
            if compiled is None:
                excluded.append(
                    Excluded(
                        relationship.uid,
                        "relationship",
                        "RELATIONSHIP_LAG_CALENDAR_UNRESOLVED",
                        policy.value,
                    )
                )
                continue
            lag_calendar = compiled.intervals
        else:
            excluded.append(
                Excluded(
                    relationship.uid,
                    "relationship",
                    "RELATIONSHIP_LAG_CALENDAR_UNRESOLVED",
                    policy.value,
                )
            )
            continue

        relationships.append(
            PlannedRelationship(
                uid=relationship.uid,
                predecessor_uid=relationship.predecessor_uid,
                successor_uid=relationship.successor_uid,
                type=relationship.type,
                lag=lag_seconds,
                lag_calendar=lag_calendar,
            )
        )

    project_start = to_seconds(project.start) if project.start is not None else window[0]
    network = Network(
        activities=tuple(activities),
        relationships=tuple(relationships),
        project_start=project_start,
        horizon=window[1],
    )
    return Plan(
        network=network,
        epoch=shared_epoch,
        calendars=calendars,
        excluded=tuple(excluded),
        snap_milestones=project.milestone_snap_policy is MilestoneSnapPolicy.NEXT_WORKING,
    )
