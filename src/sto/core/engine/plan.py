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

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sto.core.calendar.arithmetic import CompiledIntervals, intersect_intervals, normalise
from sto.core.calendar.compile import CompiledCalendar, Horizon, compile_calendars
from sto.core.model.entities import Activity, Assignment, Schedule
from sto.core.model.enums import (
    ActivityKind,
    ConstraintType,
    LagCalendar,
    MilestoneSnapPolicy,
    ProgressPolicy,
    RelationshipType,
    ScheduleDirection,
)

from .forward import ActivityTimes, forward_pass
from .network import (
    Network,
    NetworkError,
    PlannedActivity,
    PlannedRelationship,
    lag_calendar_for,
    shift_lag,
)
from .progress import ProgressState, remaining_bound


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
#: measured bounded rule of its own for ordinary zero-lag FS boundaries. The
#: supported subset is represented by native-evidence-derived bypass edges;
#: unsupported successors remain labelled ``ACTIVITY_SUCCESSOR_OF_INACTIVE``.
#: ``ACTIVITY_KIND_NOT_SCHEDULED`` is a
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
    #: The hierarchy beneath every summary row, as identifiers: the WBS nodes
    #: and activities directly under each node, in source order. The rollup
    #: reads it and nothing else does, but it belongs here rather than in the
    #: network -- a summary is not scheduled, and the network carries only what
    #: the passes place. Reading it off the canonical model twice would be two
    #: chances to disagree about what a summary contains.
    wbs_children: dict[UUID, tuple[UUID, ...]] = field(default_factory=dict)
    #: The file declared a status date that falls outside the compiled window,
    #: so the network carries none. Reported rather than dropped silently,
    #: because a schedule that loses its status date schedules its remaining
    #: work from its logic and looks like an ordinary un-progressed plan.
    status_time_outside_window: bool = False
    #: Whether resource calendars were applied to activity calendars. It is the
    #: caller's choice and not the file's, and it changes the dates on any
    #: schedule with assignments -- so a result that did not record it could
    #: not say which rules produced it.
    resource_calendars_apply: bool = True

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


def _measured_in_progress_native_shape_static_failures(
    activity: Activity,
    activity_assignments: list[Assignment],
    resource_uids: set[UUID],
    incident: list[PlannedRelationship],
    progress_policy: ProgressPolicy,
) -> tuple[str, ...] | None:
    """Evaluate the static half of the positive native-evidence contract.

    ``None`` means this is not the in-progress state to which the contract
    applies. An empty tuple means every static characteristic of the two
    controlled Microsoft Project trials is affirmatively present; it does not
    mean final eligibility until the forward-network checks below also pass.

    This predicate describes evidence eligibility, not the scheduler's general
    supported-input boundary. The engine may calculate broader shapes, but
    their late dates are labelled as assumed.
    """

    if activity.actual_start is None or activity.actual_finish is not None:
        return None

    failures: list[str] = []
    actual_duration = activity.actual_duration
    if "actual_duration_unsupported_source" in activity.source_fields:
        failures.append("actual duration is unreadable")
    elif actual_duration is None:
        failures.append("actual duration is absent")
    elif actual_duration.seconds != 0:
        failures.append("actual duration is not measured zero")
    elif actual_duration.elapsed:
        failures.append("actual duration is elapsed")

    remaining_duration = activity.remaining_duration
    if remaining_duration is None:
        failures.append("remaining duration is absent")
    elif remaining_duration.seconds <= 0:
        failures.append("remaining duration is not strictly positive")
    elif remaining_duration.elapsed:
        failures.append("remaining duration is elapsed")
    if activity.planned_duration is not None and activity.planned_duration.elapsed:
        failures.append("planned duration is elapsed")

    task_actual_work = activity.actual_work
    if "actual_work_unsupported_source" in activity.source_fields:
        failures.append("task actual work is unreadable")
    elif task_actual_work is None:
        failures.append("task actual work is absent")
    elif task_actual_work.seconds != 0:
        failures.append("task actual work is not measured zero")

    if any(
        value != 0
        for value in (
            activity.percent_complete.duration_permille,
            activity.percent_complete.work_permille,
            activity.percent_complete.physical_permille,
            activity.percent_complete.units_permille,
        )
    ):
        failures.append("reported percentage progress is outside the measured shape")

    split_markers = (activity.suspend, activity.resume)
    if split_markers not in (
        (None, None),
        (activity.actual_start, activity.actual_start),
    ):
        failures.append("Stop/Resume describes a split span")

    if len(activity_assignments) != 1:
        failures.append(
            "assignment cardinality is outside the measured one-assignment shape"
        )
    else:
        assignment = activity_assignments[0]
        resolved_resource_assignment = (
            assignment.activity_uid == activity.uid
            and assignment.resource_uid is not None
            and assignment.resource_uid in resource_uids
            and not assignment.unassigned_placeholder
        )
        if not resolved_resource_assignment:
            failures.append(
                "the measured assignment is not a resolved resource-backed assignment"
            )
        if "actual_work_unsupported_source" in assignment.source_fields:
            failures.append("assignment actual work is unreadable")
        elif assignment.source_fields.get("actual_work_source_present") != "1":
            failures.append("assignment actual work is absent")
        elif assignment.work.actual_seconds != 0:
            failures.append("assignment actual work is not measured zero")
        if assignment.percent_work_complete_permille != 0:
            failures.append(
                "assignment percentage progress is outside the measured shape"
            )

    primary = activity.primary_constraint
    if (
        primary is not None and primary.type is not ConstraintType.ASAP
    ) or activity.secondary_constraint is not None:
        failures.append("started work carries an unmeasured constraint")

    incoming = [row for row in incident if row.successor_uid == activity.uid]
    outgoing = [row for row in incident if row.predecessor_uid == activity.uid]
    if not incoming or not outgoing:
        failures.append("the measured predecessor/successor shape is absent")
    if any(
        row.type is not RelationshipType.FS or row.lag != 0
        for row in incident
    ):
        failures.append("incident logic is not ordinary zero-lag FS")
    if progress_policy is not ProgressPolicy.RETAINED_LOGIC:
        failures.append("the progress policy is not the measured retained logic")

    return tuple(failures)


def _measured_in_progress_native_shape_dynamic_failures(
    activity: Activity,
    incident: list[PlannedRelationship],
    early: dict[UUID, ActivityTimes],
    planned: PlannedActivity,
    progress_policy: ProgressPolicy,
    status_time: int | None,
) -> tuple[str, ...]:
    """Evaluate the forward-network half of the same positive contract."""

    failures: list[str] = []
    if planned.actual_start is None:
        # Static eligibility requires Actual Start. Keep this fail-closed if a
        # future planner mapping ever loses it between the canonical row and
        # the network consumed by the passes.
        failures.append("Actual Start is absent from the planned activity")
        return tuple(failures)

    for relationship in incident:
        if relationship.successor_uid != activity.uid:
            continue
        predecessor = early[relationship.predecessor_uid]
        anchor = (
            predecessor.early_finish
            if relationship.anchors_predecessor_finish
            else predecessor.early_start
        )
        landing = shift_lag(
            lag_calendar_for(relationship, planned.calendar),
            anchor,
            relationship.lag,
        )
        if landing is None or landing > planned.actual_start:
            failures.append(
                "incoming retained logic is out of sequence at Actual Start"
            )
            break

    # Ask the same policy primitive as the forward pass, isolating the status
    # floor from predecessor logic. The measured trials did not exercise a
    # usable status time that raises unfinished work beyond Actual Start.
    status_bound = remaining_bound(
        ProgressState.IN_PROGRESS,
        progress_policy,
        planned.actual_start,
        status_time,
        planned.actual_start,
    )
    if status_bound > planned.actual_start:
        failures.append("usable status date moves remaining work beyond Actual Start")

    return tuple(failures)


def _zero_lag_fs_relationship(relationship) -> bool:
    lag = relationship.lag
    return (
        relationship.type is RelationshipType.FS
        and not relationship.cross_project
        and (lag is None or (lag.seconds == 0 and not lag.elapsed))
    )


def _inactive_boundary_endpoint_is_measured(activity: Activity) -> bool:
    primary = activity.primary_constraint
    return (
        activity.active
        and not activity.manual
        and activity.actual_start is None
        and activity.actual_finish is None
        and activity.suspend is None
        and activity.resume is None
        and all(
            value == 0
            for value in (
                activity.percent_complete.duration_permille,
                activity.percent_complete.work_permille,
                activity.percent_complete.physical_permille,
                activity.percent_complete.units_permille,
            )
        )
        and (primary is None or primary.type is ConstraintType.ASAP)
        and activity.secondary_constraint is None
    )


def _inactive_middle_is_measured(activity: Activity) -> bool:
    primary = activity.primary_constraint
    planned = activity.planned_duration
    remaining = activity.remaining_duration
    return (
        not activity.active
        and activity.kind is ActivityKind.TASK
        and not activity.manual
        and activity.actual_start is None
        and activity.actual_finish is None
        and activity.suspend is None
        and activity.resume is None
        and all(
            value == 0
            for value in (
                activity.percent_complete.duration_permille,
                activity.percent_complete.work_permille,
                activity.percent_complete.physical_permille,
                activity.percent_complete.units_permille,
            )
        )
        and (primary is None or primary.type is ConstraintType.ASAP)
        and activity.secondary_constraint is None
        and planned is not None
        and not planned.elapsed
        and (remaining is None or not remaining.elapsed)
        and activity.source_fields.get("duration_unsupported_source") is None
        and activity.source_fields.get("duration_format_unsupported_source") is None
        and activity.source_fields.get("is_null_source") != "1"
    )


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
        # A coded refusal like every other reason a plan cannot be built. A
        # bare ValueError here reached the API as a server fault, because it
        # was the one refusal outside the engine's own error family.
        raise PlanError(
            "PROJECT_NO_CALENDARS",
            None,
            "the schedule carries no calendars to compile",
        )
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
    assignment_rows_by_activity: dict[UUID, list[Assignment]] = {}
    for assignment in schedule.assignments:
        if assignment.activity_uid is None:
            continue
        assignment_rows_by_activity.setdefault(assignment.activity_uid, []).append(
            assignment
        )
        if assignment.resource_uid is None:
            continue
        assignments_by_activity.setdefault(assignment.activity_uid, []).append(
            assignment.resource_uid
        )

    def to_seconds(moment: datetime) -> int:
        return int((moment - shared_epoch).total_seconds())

    assumed: list[Assumed] = []
    resource_uids = set(resources)

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
            # The row *is* scheduled -- only its second constraint is not
            # applied -- so this is an assumption about a placed activity and
            # not a disposition. Recorded as an exclusion it made the same
            # activity both scheduled and excluded, which is not a partition,
            # and which a result keyed on the activity cannot store twice.
            assumed.append(
                Assumed(
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

    raw_incoming: dict[UUID, list] = {}
    raw_outgoing: dict[UUID, list] = {}
    for relationship in schedule.relationships:
        raw_incoming.setdefault(relationship.successor_uid, []).append(relationship)
        raw_outgoing.setdefault(relationship.predecessor_uid, []).append(relationship)

    boundary_candidates: dict[UUID, tuple[object, tuple[object, ...]]] = {}
    predecessor_boundaries: dict[UUID, list[UUID]] = {}
    for inactive_uid in sorted(inactive, key=str):
        middle = activities_by_uid[inactive_uid]
        if not _inactive_middle_is_measured(middle):
            continue
        incoming_scheduled = [
            row for row in raw_incoming.get(inactive_uid, ())
            if row.predecessor_uid in scheduled
        ]
        outgoing_scheduled = [
            row for row in raw_outgoing.get(inactive_uid, ())
            if row.successor_uid in scheduled
        ]
        if len(incoming_scheduled) != 1 or len(outgoing_scheduled) not in (1, 2):
            continue
        incoming_edge = incoming_scheduled[0]
        if not _zero_lag_fs_relationship(incoming_edge):
            continue
        if any(not _zero_lag_fs_relationship(row) for row in outgoing_scheduled):
            continue
        predecessor = activities_by_uid[incoming_edge.predecessor_uid]
        successors = [activities_by_uid[row.successor_uid] for row in outgoing_scheduled]
        if not _inactive_boundary_endpoint_is_measured(predecessor):
            continue
        if any(not _inactive_boundary_endpoint_is_measured(row) for row in successors):
            continue
        # A successor reached from several inactive rows is a different fan-in
        # shape from the native matrix; leave it on the historical labelled path.
        if any(
            sum(
                1
                for incoming in raw_incoming.get(row.successor_uid, ())
                if incoming.predecessor_uid in inactive
            ) != 1
            for row in outgoing_scheduled
        ):
            continue
        boundary_candidates[inactive_uid] = (incoming_edge, tuple(outgoing_scheduled))
        predecessor_boundaries.setdefault(incoming_edge.predecessor_uid, []).append(
            inactive_uid
        )

    # Multiple inactive boundaries from one predecessor have not been measured
    # together. Remove all such candidates rather than choosing one.
    unsupported_boundary_uids = {
        inactive_uid
        for rows in predecessor_boundaries.values()
        if len(rows) != 1
        for inactive_uid in rows
    }
    for inactive_uid in unsupported_boundary_uids:
        boundary_candidates.pop(inactive_uid, None)

    supported_inactive_successor_relationships = {
        row.uid
        for _, outgoing_rows in boundary_candidates.values()
        for row in outgoing_rows
    }

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
                and relationship.uid not in supported_inactive_successor_relationships
                and relationship.successor_uid not in labelled_successors
            ):
                labelled_successors.add(relationship.successor_uid)
                # The native evidence now covers one bounded zero-lag FS
                # shape. Anything else still has no production rule and stays
                # explicitly labelled rather than inheriting that result.
                assumed.append(
                    Assumed(
                        relationship.successor_uid,
                        "activity",
                        "ACTIVITY_SUCCESSOR_OF_INACTIVE",
                        "inactive-boundary shape is outside the measured production rule",
