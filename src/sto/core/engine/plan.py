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
cohort is visible rather than looking like a clean run over fewer rows. And
nothing is assumed silently either: a row scheduled under a rule that is a
labelled assumption rather than a measured one appears in :attr:`Plan.assumed`
with a code, so a claim about the schedule can say exactly which rows it rests
on.

Two rules here are Microsoft Project's, measured on the three real schedules in
the estate rather than taken from documentation (ADR-010).

**Which calendar a task is scheduled on.** A task with no calendar of its own
and one assigned resource is scheduled on the *resource's* calendar, not the
project's; a task with its own calendar and a resource is scheduled on the
intersection of the two; ``IgnoreResourceCalendar`` restores the task's own
calendar; and a task with no resource calendar at all takes its own or the
project's. Turning that rule on took the un-progressed BOILER snapshot from one
activity agreeing with Project's stored dates to well over three hundred, and
the half-hour cluster of differences the forward-pass slice could not explain
was exactly the project calendar's 07:30 against the resources' 07:00. A task
whose resources are on **several** calendars is scheduled on their union and
reported as an assumption: Project's own answer for those rows is the envelope
of its per-assignment spans, which this pass does not compute.

**Which calendar a lag is consumed on.** The successor's own *task* calendar
when it has one, otherwise the project calendar -- never a resource calendar.
Of the fifty-seven working-time lags across KILN and CALCINER that any rule
could explain, that rule explains every one; the successor's effective
calendar, which is what this plan assumed before, explains a third of KILN's.
Both project calendars in the estate are twenty-four hours, so a lag on the
project calendar and an elapsed lag cannot be told apart here, and the choice
between them is labelled rather than claimed. The rule is Microsoft Project's
and is applied to relationships that *inherit* the project's lag policy, which
is every relationship a Microsoft file carries; a canonical relationship that
names the successor's calendar explicitly gets the calendar the successor is
scheduled on, as the enum says.

The forward pass works in whatever unit the calendars were compiled in --
integer seconds from a shared epoch, here -- so :meth:`Plan.to_datetime` is how
a coordinate becomes a wall-clock moment again. The epoch is shared across every
calendar in the plan, because coordinates from two epochs cannot be compared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sto.core.calendar.arithmetic import CompiledIntervals, intersect_intervals, normalise
from sto.core.calendar.compile import CompiledCalendar, Horizon, compile_calendars
from sto.core.model.entities import Activity, Schedule
from sto.core.model.enums import (
    ActivityKind,
    ConstraintType,
    LagCalendar,
    MilestoneSnapPolicy,
    ProgressPolicy,
    ScheduleDirection,
)

from .network import Network, NetworkError, PlannedActivity, PlannedRelationship


class PlanError(NetworkError):
    """A schedule the plan will not turn into a network, and why, by code.

    A row the plan cannot schedule is an :class:`Excluded` with a code. This
    is for the other kind: a project-wide setting that would make every row's
    answer wrong, where returning a network at all would be the defect.
    """

#: Kinds the forward pass schedules. A summary is a rollup of its children (S6),
#: and level-of-effort and hammock activities take their span from other rows
#: rather than from their own duration, so none of the three is scheduled here.
SCHEDULED_KINDS = frozenset(
    {ActivityKind.TASK, ActivityKind.START_MILESTONE, ActivityKind.FINISH_MILESTONE}
)

#: Exclusion codes that mean *we do not know when this row happens*, as
#: opposed to structural ones. A successor of such a row cannot be scheduled
#: either: dropping only the edge leaves it with no predecessor at all, and the
#: forward pass then treats it as a root and floors it at the project start --
#: earlier than the file says, which is exactly the false advancement excluding
#: the predecessor was meant to prevent.
#:
#: Two exclusions are deliberately not here. ``ACTIVITY_INACTIVE`` has a
#: measured rule of its own: the edge is dropped and the successor scheduled
#: and labelled ``ACTIVITY_SUCCESSOR_OF_INACTIVE``, because Microsoft Project
#: does schedule those rows (ADR-010). ``ACTIVITY_KIND_NOT_SCHEDULED`` is a
#: summary, a level of effort or a hammock, whose span comes from its children
#: rather than from itself; the rollup is S6's, and until then dropping the
#: edge is what the previous engine did too.
UNKNOWN_DATE_EXCLUSIONS = frozenset(
    {
        "ACTIVITY_CALENDAR_UNRESOLVED",
        "ACTIVITY_CALENDAR_EMPTY",
        "ACTIVITY_MEASURE_CALENDAR_EMPTY",
        "ACTIVITY_CONSTRAINT_INCOMPLETE",
        "ACTIVITY_DURATION_UNSUPPORTED",
        "ACTIVITY_DURATION_NON_INTEGRAL",
        "ACTIVITY_REMAINING_UNSUPPORTED",
        "ACTIVITY_DURATION_FORMAT_UNSUPPORTED",
        "ACTIVITY_MANUALLY_SCHEDULED",
        "ACTIVITY_NULL_PLACEHOLDER",
    }
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
class Assumed:
    """A row the plan schedules under a labelled assumption, and the code for it."""

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
    #: Rows scheduled under an assumption rather than a measured rule.
    assumed: tuple[Assumed, ...] = ()
    snap_milestones: bool = False
    #: The project's critical-float threshold in seconds, carried here so a
    #: caller running the passes never has to reach back into the schedule for
    #: the one number criticality depends on.
    critical_float_threshold: int = 0
    #: The project's out-of-sequence progress rule, carried for the same reason.
    #: Microsoft Project has no field for it and the migration writes retained
    #: logic, which is what Project does; a Primavera file will carry its own.
    progress_policy: ProgressPolicy = ProgressPolicy.RETAINED_LOGIC
    #: The file declared a status date that falls outside the compiled window,
    #: so the network carries none. Reported rather than dropped silently,
    #: because a schedule that loses its status date schedules its remaining
    #: work from its logic and looks like an ordinary un-progressed plan.
    status_time_outside_window: bool = False

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

    def assumed_by_code(self) -> dict[str, int]:
        """How many rows rest on each assumption."""

        counts: dict[str, int] = {}
        for row in self.assumed:
            counts[row.code] = counts.get(row.code, 0) + 1
        return counts


def _duration_seconds(activity: Activity) -> int:
    """The activity's duration in seconds, where zero really means zero.

    A row whose duration the importer could not read never reaches here: the
    eligibility pass excludes it by code, because ``None`` reaching this
    function would become zero work and let its successors advance under a
    calculation that looks ordinary.
    """

    if activity.planned_duration is None:
        return 0
    return activity.planned_duration.seconds


def _remaining_seconds(activity: Activity) -> int | None:
    """The remaining duration in seconds, or ``None`` when the file said nothing.

    The distinction is load-bearing: an activity nobody has touched has all of
    its duration left, and one reported as having none left has zero. Collapsing
    the two would either finish untouched work instantly or give completed work
    its whole duration back.
    """

    if activity.remaining_duration is None:
        return None
    return activity.remaining_duration.seconds


def build_plan(
    schedule: Schedule,
    horizon: Horizon,
    *,
    epoch: datetime | None = None,
    resource_calendars_apply: bool = True,
) -> Plan:
    """Compile the calendars once, then map every row onto them.

    ``resource_calendars_apply`` applies Microsoft Project's calendar rule for
    assigned resources, described at the top of this module and in ADR-010:
    a resource's calendar replaces the project's for a task with none of its
    own, intersects a task's own calendar, and is set aside by the task's
    ``IgnoreResourceCalendar`` flag, which the migration carries as the source
    field ``ignore_resource_calendar_source``. Off, every activity is scheduled
    on its own or the project's calendar, which is what the forward-pass slice
    first shipped and what agreed with Project on one BOILER activity in four
    hundred and fifty-one.
    """

    calendars = compile_calendars(schedule, horizon, epoch=epoch)
    if not calendars:
        raise ValueError("the schedule carries no calendars to compile")
    any_calendar = next(iter(calendars.values()))
    shared_epoch = any_calendar.epoch
    window = any_calendar.horizon
    continuous = CompiledIntervals.of((window,))

    project = schedule.project
    if project.schedule_direction is not ScheduleDirection.FROM_START:
        # Scheduling from the finish reverses which pass is authoritative for
        # every row in the network, so it is not a per-row disposition: the
        # plan refuses rather than returning an answer computed the other way
        # round and labelled as if it were the file's.
        raise PlanError(
            "PROJECT_SCHEDULED_FROM_FINISH",
            None,
            project.schedule_direction.value,
        )
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

    assumed: list[Assumed] = []

    def effective_calendar(
        activity: Activity,
    ) -> tuple[CompiledIntervals | None, CompiledIntervals | None, str, str, Assumed | None]:
        """The calendar the activity is scheduled on, by Project's rule, and the
        one its float is measured on.

        Returns the two calendars with an empty code, or ``None`` with the code
        and detail saying why: the activity named a calendar the file does not
        carry, the activity named none and the project has no default to
        inherit, or a resource named a calendar that is not there. A union over
        several resource calendars is returned with the assumption as the last
        value rather than refused -- *returned*, not recorded, because the
        activity can still be excluded further down, and an assumption is a
        statement about a row the plan scheduled.

        The measuring calendar is the task's own or the project's -- what
        Project consumes a lag on and measures slack in -- and is ``None`` when
        it is the scheduling calendar itself, so an activity with no resource
        carries one calendar and not two copies.
        """

        unresolved = "ACTIVITY_CALENDAR_UNRESOLVED"
        own: CompiledIntervals | None = None
        if activity.calendar_uid is not None:
            compiled = calendars.get(activity.calendar_uid)
            if compiled is None:
                return (
                    None,
                    None,
                    unresolved,
                    f"activity calendar {activity.calendar_uid} is not in the file",
                    None,
                )
            own = compiled.intervals
        elif project.default_calendar_uid is not None:
            compiled = calendars.get(project.default_calendar_uid)
            if compiled is None:
                return (
                    None,
                    None,
                    unresolved,
                    "the project default calendar is not in the file",
                    None,
                )
        else:
            return (
                None,
                None,
                unresolved,
                "the activity names no calendar and the project has no default",
                None,
            )
        fallback = own if own is not None else compiled.intervals
        measure = CompiledIntervals.of(fallback.intervals)

        ignore = activity.source_fields.get("ignore_resource_calendar_source") == "1"
        if not resource_calendars_apply or ignore:
            return measure, None, "", "", None

        resource_calendars: list[UUID] = []
        for resource_uid in assignments_by_activity.get(activity.uid, []):
            resource = resources.get(resource_uid)
            if resource is None or resource.calendar_uid is None:
                continue
            if resource.calendar_uid not in resource_calendars:
                resource_calendars.append(resource.calendar_uid)
        if not resource_calendars:
            return measure, None, "", "", None

        resolved: list[CompiledIntervals] = []
        for calendar_uid in resource_calendars:
            resource_calendar = calendars.get(calendar_uid)
            if resource_calendar is None:
                return (
                    None,
                    None,
                    unresolved,
                    f"resource calendar {calendar_uid} is not in the file",
                    None,
                )
            resolved.append(resource_calendar.intervals)

        if len(resolved) == 1:
            if own is None:
                # A task with no calendar of its own is scheduled on its
                # resource's, not the project's -- the rule that closed the
                # half-hour cluster on BOILER.
                return CompiledIntervals.of(resolved[0].intervals), measure, "", "", None
            return (
                CompiledIntervals.of(intersect_intervals(own.intervals, resolved[0].intervals)),
                measure,
                "",
                "",
                None,
            )

        # Several resource calendars: Project schedules each assignment on its
        # own calendar and the task spans their envelope. The union of the
        # calendars is the assumption that stands in for that until assignments
        # are scheduled, and it is recorded per row rather than applied silently.
        merged: list[tuple[int, int]] = []
        for calendar in resolved:
            merged.extend(calendar.intervals)
        united = CompiledIntervals.of(normalise(merged))
        if own is not None:
            united = CompiledIntervals.of(intersect_intervals(own.intervals, united.intervals))
        pending = Assumed(
            activity.uid,
            "activity",
            "ACTIVITY_RESOURCE_CALENDARS_UNITED",
            f"{len(resolved)} distinct resource calendars",
        )
        return united, measure, "", "", pending

    activities: list[PlannedActivity] = []
    activities_by_uid = {activity.uid: activity for activity in schedule.activities}
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
        unsupported = activity.source_fields.get("duration_unsupported_source")
        if unsupported is not None:
            # The file gave a duration and the importer could not read it.
            # Not zero work: unknown work. Scheduling it as zero would let
            # every successor advance under a calculation that looks ordinary.
            excluded.append(
                Excluded(
                    activity.uid,
                    "activity",
                    "ACTIVITY_DURATION_" + activity.source_fields.get(
                        "duration_unsupported_reason", "DURATION_UNSUPPORTED"
                    ).removeprefix("DURATION_"),
                    unsupported,
                )
            )
            continue
        remaining_unsupported = activity.source_fields.get(
            "remaining_duration_unsupported_source"
        )
        if remaining_unsupported is not None:
            excluded.append(
                Excluded(
                    activity.uid,
                    "activity",
                    "ACTIVITY_REMAINING_UNSUPPORTED",
                    remaining_unsupported,
                )
            )
            continue
        unknown_format = activity.source_fields.get("duration_format_unsupported_source")
        if unknown_format is not None:
            # The code decides whether the span runs on the calendar or on the
            # clock. An unknown one leaves that unanswered, so the row is not
            # scheduled as though the answer were "working time".
            excluded.append(
                Excluded(
                    activity.uid,
                    "activity",
                    "ACTIVITY_DURATION_FORMAT_UNSUPPORTED",
                    unknown_format,
                )
            )
            continue
        if activity.source_fields.get("is_null_source") == "1":
            # Project's null placeholder: a gap it keeps in the task list, not
            # work. The migration dropped the flag and it looked ordinary.
            excluded.append(Excluded(activity.uid, "activity", "ACTIVITY_NULL_PLACEHOLDER"))
            continue
        if activity.manual:
            # A manually scheduled task holds the dates a planner typed;
            # Project does not move it and this pass has no rule for one, so
            # it is reported rather than scheduled as if it were automatic.
            excluded.append(Excluded(activity.uid, "activity", "ACTIVITY_MANUALLY_SCHEDULED"))
            continue

        elapsed = bool(
            (activity.planned_duration is not None and activity.planned_duration.elapsed)
            or (activity.remaining_duration is not None and activity.remaining_duration.elapsed)
        )
        calendar, measure, code, detail, pending_assumption = effective_calendar(activity)
        if calendar is None:
            excluded.append(Excluded(activity.uid, "activity", code, detail))
            continue
        if not calendar.intervals:
            excluded.append(Excluded(activity.uid, "activity", "ACTIVITY_CALENDAR_EMPTY"))
            continue
        if measure is not None and not measure.intervals:
            # The work has somewhere to go -- a resource calendar -- but the
            # calendar its slack is measured on has no working time, so every
            # float would come out as zero and the row as critical. That is
            # not a measurement; the row is excluded with its own code.
            excluded.append(Excluded(activity.uid, "activity", "ACTIVITY_MEASURE_CALENDAR_EMPTY"))
            continue

        if elapsed:
            # Elapsed time counts every hour on the clock, working or not
            # (Microsoft's DurationFormat reference says so in as many words),
            # so the span is placed on the continuous calendar. Slack is still
            # measured where ADR-010 measures it. The rule is the format's
            # documented meaning rather than a measurement of these files -- no
            # elapsed row here has ever been scheduled before -- so the row is
            # labelled, not silently claimed.
            measure = measure if measure is not None else CompiledIntervals.of(
                calendar.intervals
            )
            calendar = continuous
            pending_assumption = Assumed(
                activity.uid,
                "activity",
                "ACTIVITY_DURATION_ELAPSED",
                "elapsed duration placed on the continuous calendar",
            )

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
                actual_start=(
                    None if activity.actual_start is None
                    else to_seconds(activity.actual_start)
                ),
                actual_finish=(
                    None if activity.actual_finish is None
                    else to_seconds(activity.actual_finish)
                ),
                remaining_duration=_remaining_seconds(activity),
                measure_calendar=measure,
            )
        )
        scheduled.add(activity.uid)
        if pending_assumption is not None:
            assumed.append(pending_assumption)

    # A row whose dates are unknown takes its successors with it. Walked to a
    # fixed point, so a chain behind one unreadable duration is reported rather
    # than half-reported, and the rows come out in declaration order.
    unknown = {
        row.uid
        for row in excluded
        if row.kind == "activity" and row.code in UNKNOWN_DATE_EXCLUSIONS
    }
    if unknown:
        successors_of: dict[UUID, list[UUID]] = {}
        for relationship in schedule.relationships:
            successors_of.setdefault(relationship.predecessor_uid, []).append(
                relationship.successor_uid
            )
        # Work that has finished is where the file says it finished: both
        # passes pin a complete activity to its actual dates and neither reads
        # its predecessors (ADR-009). So a completed successor is not cut --
        # that would throw away known progress -- and the cut does not travel
        # through it either, because everything after it reads *its* actual
        # finish, which is known.
        completed = {
            row.uid for row in schedule.activities if row.actual_finish is not None
        }
        frontier = list(unknown)
        cut: dict[UUID, UUID] = {}
        while frontier:
            predecessor_uid = frontier.pop()
            for successor_uid in successors_of.get(predecessor_uid, ()):
                if successor_uid in completed or successor_uid not in scheduled:
                    continue
                if successor_uid not in cut:
                    cut[successor_uid] = predecessor_uid
                    frontier.append(successor_uid)
        if cut:
            scheduled -= cut.keys()
            activities = [row for row in activities if row.uid not in cut]
            assumed = [row for row in assumed if row.uid not in cut]
            for activity in schedule.activities:
                if activity.uid in cut:
                    excluded.append(
                        Excluded(
                            activity.uid,
                            "activity",
                            "ACTIVITY_PREDECESSOR_NOT_SCHEDULED",
                            str(cut[activity.uid]),
                        )
                    )

    activity_calendars = {row.uid: row.calendar for row in activities}

    def lag_calendar_of(activity_uid: UUID) -> tuple[CompiledIntervals | None, bool]:
        """The calendar Project consumes a working lag on: the successor's own
        task calendar when it has one, otherwise the project's. A resource
        calendar never applies to a lag, which is the half of the rule the
        forward-pass slice did not have. The second value says the project's
        calendar was the answer -- a choice the estate cannot tell from elapsed
        time (ADR-010), so the caller labels it."""

        activity = activities_by_uid[activity_uid]
        own = activity.calendar_uid
        uid = own or project.default_calendar_uid
        compiled = calendars.get(uid) if uid is not None else None
        return (None if compiled is None else compiled.intervals), own is None

    relationships: list[PlannedRelationship] = []
    inactive = {row.uid for row in excluded if row.code == "ACTIVITY_INACTIVE"}
    # ``Plan.assumed`` counts rows, so a successor with several inactive
    # predecessors is labelled once, not once per edge.
    labelled_successors: set[UUID] = set()
    for relationship in schedule.relationships:
        if (
            relationship.predecessor_uid not in scheduled
            or relationship.successor_uid not in scheduled
        ):
            excluded.append(
                Excluded(relationship.uid, "relationship", "RELATIONSHIP_ENDPOINT_NOT_SCHEDULED")
            )
            if (
                relationship.predecessor_uid in inactive
                and relationship.successor_uid in scheduled
                and relationship.successor_uid not in labelled_successors
            ):
                labelled_successors.add(relationship.successor_uid)
                # What Microsoft Project does with the successor of an
                # inactive task is not one rule on the files here: of the
                # successors measured across the BOILER family and KILN, some
                # sit where the inactive task's own predecessors put them, some
                # where their other predecessors do, and some where nothing
                # measured puts them. The edge is dropped and the successor is
                # labelled, so a claim about the schedule can name these rows.
                assumed.append(
                    Assumed(
                        relationship.successor_uid,
                        "activity",
                        "ACTIVITY_SUCCESSOR_OF_INACTIVE",
                        "scheduled as if the edge from the inactive task did not exist",
                    )
                )
            continue

        lag = relationship.lag
        lag_seconds = 0 if lag is None else lag.seconds
        policy = relationship.lag_calendar
        # The Microsoft rule -- task calendar, else project calendar, never a
        # resource's -- was measured on files whose relationships all inherit
        # the project's policy, and it is applied to exactly those. A canonical
        # relationship that names the successor's calendar itself means the
        # calendar the successor is scheduled on, which is what the enum says
        # and what a Primavera file would mean by it.
        inherited = policy is LagCalendar.INHERIT_PROJECT_POLICY
        if inherited:
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
        elif policy is LagCalendar.SUCCESSOR and not inherited:
            lag_calendar = activity_calendars[relationship.successor_uid]
        elif policy is LagCalendar.SUCCESSOR:
            lag_calendar, on_project_calendar = lag_calendar_of(relationship.successor_uid)
            if lag_calendar is None:
                excluded.append(
                    Excluded(
                        relationship.uid,
                        "relationship",
                        "RELATIONSHIP_LAG_CALENDAR_UNRESOLVED",
                        policy.value,
                    )
                )
                continue
            if on_project_calendar:
                # Every measured lag is explained by the successor's task
                # calendar or the project's, but every project calendar in the
                # estate runs twenty-four hours, so "project calendar" and
                # "elapsed" have never been told apart. The choice is labelled
                # rather than presented as measured.
                assumed.append(
                    Assumed(
                        relationship.uid,
                        "relationship",
                        "RELATIONSHIP_LAG_ON_PROJECT_CALENDAR",
                        "successor has no task calendar; project calendar and "
                        "elapsed time are not distinguishable on this estate",
                    )
                )
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

    # An assumption is a statement about a row the plan scheduled. One about
    # an excluded row would count in ``assumed_by_code`` against a calculation
    # it took no part in, so the plan refuses to carry it rather than report it.
    for row in assumed:
        if row.kind == "activity" and row.uid not in scheduled:
            raise ValueError(
                f"assumption {row.code} names activity {row.uid}, which the plan did not schedule"
            )

    if project.start is None:
        # Every floor in this pass is the project start: a task nothing else
        # places sits there, and so does the start of a task whose
        # predecessors bound only its finish. Substituting the compiled
        # window's first coordinate made all of those the caller's choice
        # rather than the schedule's -- move the window a day and the dates
        # move a day. A schedule that declares no start has no such anchor,
        # and the plan says so instead of inventing one.
        raise PlanError(
            "PROJECT_START_MISSING",
            None,
            "the schedule declares no start, so there is no coordinate to floor a task at",
        )
    project_start = to_seconds(project.start)
    status_time: int | None = None
    status_outside = False
    if project.status_date is not None:
        candidate = to_seconds(project.status_date)
        if project_start <= candidate <= window[1]:
            status_time = candidate
        else:
            status_outside = True

    network = Network(
        activities=tuple(activities),
        relationships=tuple(relationships),
        project_start=project_start,
        horizon=window[1],
        status_time=status_time,
    )
    return Plan(
        network=network,
        epoch=shared_epoch,
        calendars=calendars,
        excluded=tuple(excluded),
        assumed=tuple(assumed),
        snap_milestones=project.milestone_snap_policy is MilestoneSnapPolicy.NEXT_WORKING,
        critical_float_threshold=project.critical_float_threshold_seconds,
        progress_policy=project.progress_policy,
        status_time_outside_window=status_outside,
    )
