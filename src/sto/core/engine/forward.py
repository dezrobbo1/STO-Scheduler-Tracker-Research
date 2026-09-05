"""The forward pass: earliest start and finish over all four relationship types.

One traversal in topological order. Each activity takes a lower bound on its
start and a lower bound on its finish from its predecessors, raises either by a
constraint, and is then placed at the earliest span its own calendar allows.

The four types differ only in which end they read and which end they bound:

=====  ==========================  =========================
Type   reads the predecessor's     bounds the successor's
=====  ==========================  =========================
FS     finish                      start
SS     start                       start
FF     finish                      finish
SF     start                       finish
=====  ==========================  =========================

Signed lag is consumed on the relationship's lag calendar -- by default the
successor's own, which is both the canonical model's policy for Microsoft files
and what the conformance corpus declares. Positive lag walks the calendar
forward, negative lag walks it backward, and **zero lag returns the anchor
coordinate untouched even when it lies in a gap**: snapping is a property of
placement, not of lag, and doing it in both places moves a successor a whole
interval too far.

Placement is :func:`~sto.core.calendar.arithmetic.earliest_span`, which already
answers "the earliest span whose start is at or after one bound and whose finish
is at or after another" -- exactly an SS-driven start combined with an FF-driven
finish. It is not re-derived here.

Milestones are the one place where two defensible rules exist. A zero-duration
activity has no span to place, only a coordinate. The previous engine puts it
exactly on its predecessor's finish without snapping, which routinely lands it
on an interval's exclusive edge; ``earliest_span`` snaps a zero duration to the
next working coordinate. Rather than choose, the pass reads
:class:`~sto.core.model.enums.MilestoneSnapPolicy` off the project -- which
exists in the canonical model for exactly this question and defaults to not
snapping. Both behaviours are reachable and neither is assumed.

Progress. An activity that reports an actual date is not scheduled from its
duration. A **complete** one keeps its two actual dates exactly -- nothing
recomputes them -- and an **in progress** one keeps its actual start while its
*remaining* duration is placed as a fresh span from the status date. Successors
read the resulting forecast finish, so an activity that started late drags its
chain behind it. Which bound that remaining span obeys when work began out of
sequence is the project's progress policy; the three states and the policy both
live in :mod:`sto.core.engine.progress`, and this pass asks that module where
remaining work may begin and then places it exactly as it places everything
else.

What this pass does not do, and does not pretend to: no backward pass, no float,
no criticality, and no rollup to summary tasks.
Constraints that cannot pull an early date earlier -- ALAP, SNLT, FNLT -- are
carried through to :attr:`ForwardPass.deferred_constraints` rather than silently
treated as ASAP, so the backward-pass slice receives them instead of
rediscovering them.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from uuid import UUID

from sto.core.calendar.arithmetic import (
    add_working,
    earliest_span,
    next_working,
    sub_working,
)
from sto.core.hashing import canonical_sha256
from sto.core.model.enums import ConstraintType, ProgressPolicy

from .network import (
    DEFERRED_CONSTRAINTS,
    ForwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    shift_lag,
)
from .progress import ProgressState, remaining_bound, require_supported, state_of

#: Why an activity's start sits where it does.
FROM_PROJECT_START = "project_start"
FROM_RELATIONSHIP = "relationship"
FROM_CONSTRAINT = "constraint"
#: A complete activity sits on its reported dates and on nothing else.
FROM_ACTUALS = "actuals"
#: Remaining work held at the status date rather than by any predecessor.
FROM_STATUS_TIME = "status_time"

#: Named on the fingerprint so a stored answer says which pass produced it.
#: Version two carries the remaining start, so a progressed schedule's answer
#: cannot hash the same as the unprogressed one it was computed from.
FORWARD_PASS_PROFILE = "sto-forward-pass-v2"


@dataclass(frozen=True, slots=True)
class ActivityTimes:
    """One activity's earliest span and what put it there.

    ``remaining_start`` is where the *unfinished* part of the work begins, and
    is set only for an activity that has started and not finished -- the one
    state in which a span has two beginnings, the one the work actually had and
    the one its remaining work will have. It is ``None`` everywhere else, which
    is the corpus's own convention: the status cases declare a
    ``remaining_start`` for exactly the in-progress activities and omit it for
    the rest, so a disagreement about the state fails as loudly as a
    disagreement about a date.
    """

    uid: UUID
    early_start: int
    early_finish: int
    driving_relationship_uid: UUID | None = None
    source: str = FROM_PROJECT_START
    state: ProgressState = ProgressState.NOT_STARTED
    remaining_start: int | None = None


@dataclass(frozen=True, slots=True)
class DeferredConstraint:
    """A constraint recognised, carried, and deliberately not applied here."""

    activity_uid: UUID
    type: ConstraintType


@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    """A hard constraint that overrode precedence, and the logic it broke.

    A must-start-on or must-finish-on date wins against its predecessors -- that
    is what makes it hard in the canonical model -- so what it displaced is
    reported rather than lost.
    """

    activity_uid: UUID
    type: ConstraintType
    coordinate: int
    logic_required: int


@dataclass(frozen=True, slots=True)
class ForwardPass:
    """Earliest dates for every activity, and the evidence for them."""

    times: tuple[ActivityTimes, ...]
    order: tuple[UUID, ...]
    project_start: int
    project_finish: int
    deferred_constraints: tuple[DeferredConstraint, ...] = ()
    constraint_violations: tuple[ConstraintViolation, ...] = ()
    fingerprint: str = ""

    def by_uid(self) -> dict[UUID, ActivityTimes]:
        return {row.uid: row for row in self.times}

    def driving_relationships(self) -> tuple[UUID, ...]:
        """Every relationship that placed an activity, in topological order."""

        seen: list[UUID] = []
        for row in self.times:
            uid = row.driving_relationship_uid
            if uid is not None and uid not in seen:
                seen.append(uid)
        return tuple(seen)

    def by_state(self) -> dict[ProgressState, tuple[UUID, ...]]:
        """The activities in each progress state, in topological order."""

        grouped: dict[ProgressState, list[UUID]] = {state: [] for state in ProgressState}
        for row in self.times:
            grouped[row.state].append(row.uid)
        return {state: tuple(uids) for state, uids in grouped.items()}

    def complete_activities(self) -> frozenset[UUID]:
        """The activities reported finished -- what criticality has to exclude."""

        return frozenset(
            row.uid for row in self.times if row.state is ProgressState.COMPLETE
        )


def _topological_order(network: Network) -> tuple[UUID, ...]:
    """Kahn's algorithm, ties broken by declaration order, cycles refused by code."""

    position = {activity.uid: index for index, activity in enumerate(network.activities)}
    successors = network.successors()
    indegree = {activity.uid: 0 for activity in network.activities}
    for relationship in network.relationships:
        indegree[relationship.successor_uid] += 1

    ready = deque(
        sorted(
            (uid for uid, count in indegree.items() if count == 0),
            key=position.__getitem__,
        )
    )
    order: list[UUID] = []
    while ready:
        uid = ready.popleft()
        order.append(uid)
        released: list[UUID] = []
        for relationship in successors[uid]:
            indegree[relationship.successor_uid] -= 1
            if indegree[relationship.successor_uid] == 0:
                released.append(relationship.successor_uid)
        ready.extend(sorted(released, key=position.__getitem__))

    if len(order) != len(network.activities):
        unresolved = sorted(
            (uid for uid, count in indegree.items() if count > 0),
            key=position.__getitem__,
        )
        raise ForwardPassError(
            "SCHEDULE_CYCLE",
            unresolved[0] if unresolved else None,
            f"{len(unresolved)} activities never reach indegree zero",
        )
    return tuple(order)


def _bounds(
    activity: PlannedActivity,
    incoming: tuple[PlannedRelationship, ...],
    placed: dict[UUID, ActivityTimes],
    project_start: int,
) -> tuple[int, int, UUID | None, UUID | None]:
    """Lower bounds on start and finish from precedence, and what drove each.

    A relationship becomes the driver when it raises its bound, or when it is
    the first to reach a bound nothing else has claimed. A later tie does not
    displace an earlier claim, so the answer follows declaration order.
    """

    start_bound = project_start
    finish_bound = project_start
    start_driver: UUID | None = None
    finish_driver: UUID | None = None

    for relationship in incoming:
        predecessor = placed[relationship.predecessor_uid]
        anchor = (
            predecessor.early_finish
            if relationship.anchors_predecessor_finish
            else predecessor.early_start
        )
        calendar = (
            relationship.lag_calendar
            if relationship.lag_calendar is not None
            else activity.calendar
        )
        shifted = shift_lag(calendar, anchor, relationship.lag)
        if shifted is None:
            raise ForwardPassError(
                "SCHEDULE_LAG_UNREACHABLE",
                relationship.uid,
                f"lag {relationship.lag} from {anchor} leaves the calendar",
            )
        if relationship.bounds_successor_start:
            if shifted > start_bound or (start_driver is None and shifted == start_bound):
                start_bound, start_driver = shifted, relationship.uid
        elif shifted > finish_bound or (finish_driver is None and shifted == finish_bound):
            finish_bound, finish_driver = shifted, relationship.uid

    return start_bound, finish_bound, start_driver, finish_driver


def forward_pass(
    network: Network,
    *,
    snap_milestones: bool = False,
    progress_policy: ProgressPolicy = ProgressPolicy.RETAINED_LOGIC,
) -> ForwardPass:
    """Earliest start and finish for every activity in ``network``.

    ``snap_milestones`` carries the project's milestone snap policy: when false
    a zero-duration activity keeps the exact coordinate its logic gives it, and
    when true it moves to the next working coordinate on its own calendar.

    ``progress_policy`` carries the project's out-of-sequence rule. It matters
    only for an activity that has started and not finished, and only when a
    predecessor of it is unfinished; on a schedule with no actual dates every
    policy gives the same answer. ``actual_dates`` is refused rather than
    guessed at -- see :mod:`sto.core.engine.progress`.
    """

    network.validate()
    require_supported(progress_policy, network.is_progressed)
    order = _topological_order(network)
    by_uid = network.activity_by_uid()
    incoming = network.predecessors()

    placed: dict[UUID, ActivityTimes] = {}
    deferred: list[DeferredConstraint] = []
    violations: list[ConstraintViolation] = []

    for uid in order:
        activity = by_uid[uid]
        start_bound, finish_bound, start_driver, finish_driver = _bounds(
            activity, incoming[uid], placed, network.project_start
        )
        logic_start, logic_finish = start_bound, finish_bound

        constraint = activity.constraint_type
        coordinate = activity.constraint_coordinate
        state = state_of(activity)
        if constraint in DEFERRED_CONSTRAINTS:
            deferred.append(DeferredConstraint(uid, constraint))

        if state is not ProgressState.NOT_STARTED:
            # An actual date is a fact and a constraint is an intention, so
            # reported work is placed on what happened. A deferred constraint is
            # still recorded above, so a file that carries one is never silently
            # dropped -- it is reported as not having been applied.
            placed[uid] = _place_reported(
                activity,
                state,
                start_bound,
                finish_bound,
                start_driver,
                finish_driver,
                network,
                snap_milestones,
                progress_policy,
            )
            continue

        pinned: str | None = None
        constrained = False
        if constraint in DEFERRED_CONSTRAINTS:
            pass
        elif constraint is ConstraintType.SNET and coordinate is not None:
            if coordinate > start_bound:
                start_bound, start_driver, constrained = coordinate, None, True
        elif constraint is ConstraintType.FNET and coordinate is not None:
            if coordinate > finish_bound:
                finish_bound, finish_driver, constrained = coordinate, None, True
        elif constraint is ConstraintType.MSO and coordinate is not None:
            pinned = "start"
        elif constraint is ConstraintType.MFO and coordinate is not None:
            pinned = "finish"

        start, finish = _place(
            activity,
            activity.remaining,
            start_bound,
            finish_bound,
            network.horizon,
            snap_milestones,
            pinned,
            coordinate,
        )

        driver: UUID | None
        if pinned is not None:
            required = logic_start if pinned == "start" else logic_finish
            actual = start if pinned == "start" else finish
            if required > actual and coordinate is not None:
                violations.append(ConstraintViolation(uid, constraint, coordinate, required))
            source, driver = FROM_CONSTRAINT, None
        elif constrained:
            source, driver = FROM_CONSTRAINT, None
        else:
            driver = _driver(
                activity,
                activity.remaining,
                start_bound,
                finish_bound,
                start_driver,
                finish_driver,
                network.project_start,
                network.horizon,
            )
            source = FROM_RELATIONSHIP if driver is not None else FROM_PROJECT_START

        placed[uid] = ActivityTimes(uid, start, finish, driver, source, state)

    times = tuple(placed[uid] for uid in order)
    project_finish = max((row.early_finish for row in times), default=network.project_start)
    return ForwardPass(
        times=times,
        order=order,
        project_start=network.project_start,
        project_finish=project_finish,
        deferred_constraints=tuple(deferred),
        constraint_violations=tuple(violations),
        fingerprint=_fingerprint(times, network.project_start, project_finish),
    )


def _place(
    activity: PlannedActivity,
    duration: int,
    start_bound: int,
    finish_bound: int,
    horizon: int,
    snap_milestones: bool,
    pinned: str | None,
    coordinate: int | None,
) -> tuple[int, int]:
    """A span of ``duration``, or a refusal by code when the horizon cannot hold it.

    ``duration`` is passed rather than read off the activity because the pass
    places two different lengths: the whole duration of work nobody has touched,
    and the *remaining* duration of work already under way. A zero-length span
    is a coordinate either way, which is why the milestone rule reads the length
    being placed rather than the activity's declared duration.
    """

    calendar = activity.calendar
    is_milestone = duration == 0

    if pinned is not None:
        if coordinate is None:
            raise ForwardPassError(
                "SCHEDULE_CONSTRAINT_INCOMPLETE",
                activity.uid,
                activity.constraint_type.value,
            )
        if pinned == "start":
            finish = (
                coordinate
                if is_milestone
                else add_working(calendar, coordinate, duration)
            )
            if finish is None or finish > horizon:
                raise ForwardPassError(
                    "SCHEDULE_HORIZON_EXCEEDED", activity.uid, "must start on"
                )
            return coordinate, finish
        start = (
            coordinate
            if is_milestone
            else sub_working(calendar, coordinate, duration)
        )
        if start is None or coordinate > horizon:
            raise ForwardPassError(
                "SCHEDULE_HORIZON_EXCEEDED", activity.uid, "must finish on"
            )
        return start, coordinate

    if is_milestone:
        moment = max(start_bound, finish_bound)
        if snap_milestones:
            snapped = next_working(calendar, moment)
            if snapped is None:
                raise ForwardPassError(
                    "SCHEDULE_HORIZON_EXCEEDED", activity.uid, "milestone snap"
                )
            moment = snapped
        if moment > horizon:
            raise ForwardPassError("SCHEDULE_HORIZON_EXCEEDED", activity.uid, "milestone")
        return moment, moment

    span = earliest_span(calendar, start_bound, finish_bound, duration, horizon)
    if span is None:
        raise ForwardPassError(
            "SCHEDULE_HORIZON_EXCEEDED",
            activity.uid,
            f"duration {duration} from {start_bound}",
        )
    return span


def _driver(
    activity: PlannedActivity,
    duration: int,
    start_bound: int,
    finish_bound: int,
    start_driver: UUID | None,
    finish_driver: UUID | None,
    project_start: int,
    horizon: int,
) -> UUID | None:
    """Which bound actually placed the activity.

    The finish bound drove only when the start bound alone could not reach it.
    Answered by placing the activity a second time without the finish bound,
    rather than by reasoning about where the calendar's gaps fall.
    """

    if finish_driver is None:
        return start_driver
    if start_driver is None:
        return finish_driver
    without_finish = earliest_span(
        activity.calendar, start_bound, project_start, duration, horizon
    )
    if without_finish is not None and without_finish[1] >= finish_bound:
        return start_driver
    return finish_driver


def _place_reported(
    activity: PlannedActivity,
    state: ProgressState,
    start_bound: int,
    finish_bound: int,
    start_driver: UUID | None,
    finish_driver: UUID | None,
    network: Network,
    snap_milestones: bool,
    progress_policy: ProgressPolicy,
) -> ActivityTimes:
    """Where an activity that has reported work sits, and what put it there.

    A complete activity is its two actual dates and nothing else: no placement,
    no calendar, no predecessors. An in-progress one keeps its actual start and
    has its remaining duration placed as a fresh span, bounded by whatever
    :func:`~sto.core.engine.progress.remaining_bound` allows under the project's
    policy.

    A relationship is reported as driving that span only when it actually held
    it: under ``progress_override`` nothing does, and under retained logic a
    predecessor overtaken by the status date did not drive anything. Saying
    otherwise would put an edge in the driving set that a planner cannot act on.
    """

    if state is ProgressState.COMPLETE:
        if activity.actual_start is None or activity.actual_finish is None:
            raise ForwardPassError("SCHEDULE_ACTUAL_FINISH_WITHOUT_START", activity.uid)
        return ActivityTimes(
            activity.uid,
            activity.actual_start,
            activity.actual_finish,
            None,
            FROM_ACTUALS,
            state,
            None,
        )

    if activity.actual_start is None:
        raise ForwardPassError("SCHEDULE_ACTUALS_INCOHERENT", activity.uid)
    status_time = network.status_time
    start_floor = remaining_bound(state, progress_policy, start_bound, status_time)
    finish_floor = remaining_bound(state, progress_policy, finish_bound, status_time)

    if progress_policy is ProgressPolicy.PROGRESS_OVERRIDE:
        start_driver = finish_driver = None
    elif status_time is not None:
        if status_time > start_bound:
            start_driver = None
        if status_time > finish_bound:
            finish_driver = None

    remaining = activity.remaining
    remaining_start, finish = _place(
        activity,
        remaining,
        start_floor,
        finish_floor,
        network.horizon,
        snap_milestones,
        None,
        None,
    )
    driver = _driver(
        activity,
        remaining,
        start_floor,
        finish_floor,
        start_driver,
        finish_driver,
        network.project_start,
        network.horizon,
    )
    if driver is not None:
        source = FROM_RELATIONSHIP
    elif status_time is not None:
        source = FROM_STATUS_TIME
    else:
        source = FROM_PROJECT_START
    return ActivityTimes(
        activity.uid,
        activity.actual_start,
        finish,
        driver,
        source,
        state,
        remaining_start,
    )


def _fingerprint(
    times: tuple[ActivityTimes, ...], project_start: int, project_finish: int
) -> str:
    """A hash of the answer, so two runs are compared without comparing objects."""

    return canonical_sha256(
        {
            "profile": FORWARD_PASS_PROFILE,
            "project_start": project_start,
            "project_finish": project_finish,
            "times": sorted(
                [str(row.uid), row.early_start, row.early_finish, row.remaining_start]
                for row in times
            ),
        }
    )
