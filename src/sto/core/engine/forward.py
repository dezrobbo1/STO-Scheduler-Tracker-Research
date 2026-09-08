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
*remaining* duration is placed as a fresh span from the status date, and never
from before the actual start. Successors read the resulting forecast finish, so
an activity that started late drags its chain behind it. Which bound that
remaining span obeys when work began out of sequence is the project's progress
policy; the three states and the policy both live in
:mod:`sto.core.engine.progress`, and this pass asks that module where remaining
work may begin and then places it exactly as it places everything else.

A constraint on an activity that has started is **reported, not applied**. An
actual date is a fact and a constraint is an intention, and what a finish-side
constraint should do to the remaining span of work already under way has no
corpus case and no real file to measure it on. Rather than treat such a row as
unconstrained, the constraint is carried to
:attr:`ForwardPass.deferred_constraints` so that a file carrying one is never
silently scheduled as if it did not.

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
    lag_calendar_for,
    DEFERRED_CONSTRAINTS,
    ForwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    shift_lag,
)
from .progress import (
    ProgressState,
    relationship_binds,
    remaining_bound,
    require_supported,
    state_of,
)

#: Why an activity's start sits where it does.
FROM_PROJECT_START = "project_start"
FROM_RELATIONSHIP = "relationship"
FROM_CONSTRAINT = "constraint"
#: A complete activity sits on its reported dates and on nothing else.
FROM_ACTUALS = "actuals"
#: Remaining work held at the status date rather than by any predecessor.
FROM_STATUS_TIME = "status_time"

#: Named on the fingerprint so a stored answer says which pass produced it.
#: Version two carried the remaining start, so a progressed schedule's answer
#: cannot hash the same as the unprogressed one it was computed from; version
#: three carries the progress state too, so an activity completed on exactly
#: its planned dates does not hash the same as one that has not begun.
FORWARD_PASS_PROFILE = "sto-forward-pass-v3"


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
    """A constraint recognised, carried, and deliberately not applied here.

    Either a type this pass cannot act on -- ALAP, SNLT, FNLT -- or any dated
    constraint on an activity that has already started, whose remaining span
    is placed on its actuals and its logic rather than on an intention.
    """

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
    #: Activities this pass placed on the project start although they have
    #: predecessors -- the rows resting on the fallback ADR-010's amendment
    #: records as an assumption rather than a measurement. Recorded here
    #: because only the pass knows it: the plan can see that no edge bounds a
    #: row's start, but not whether a constraint, an actual date or the row's
    #: own duration then decided where it went. Three attempts at deciding it
    #: from the plan alone each named rows the fallback never reached.
    unbounded_starts: tuple[UUID, ...] = ()
    fingerprint: str = ""
    #: :meth:`Network.fingerprint` of the network this was computed over, so
    #: the backward pass and the float can refuse a result from another one.
    network_fingerprint: str = ""
    #: The progress policy this pass ran under. The network fingerprint does
    #: not carry it -- the policy is an argument, not a fact about the network
    #: -- so the backward pass reads it from here rather than defaulting it a
    #: second time, and refuses a caller who names a different one.
    progress_policy: ProgressPolicy = ProgressPolicy.RETAINED_LOGIC
    #: Whether zero-length spans were moved to the next productive coordinate.
    #: Criticality carries the same placement domain into free float: a
    #: snapped milestone cannot claim movement to a coordinate from which the
    #: forward pass could no longer place it.
    snap_milestones: bool = False

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
    base: int,
    unbounded_floor: int,
) -> tuple[int, int, UUID | None, UUID | None]:
    """Lower bounds on start and finish from precedence, and what drove each.

    ``base`` is where the bounds begin before any predecessor is read: the
    project start for untouched work with **no predecessors**, the **actual
    start** for work already under way, and ``None`` -- no floor at all -- for
    untouched work that has predecessors, whose bounds come from them alone.
    Both halves are what the real files show. The project start is where
    Microsoft Project puts a task nothing else places; a task with a
    predecessor is placed by that predecessor even when a lead puts it
    *before* the project start, and the un-progressed BOILER snapshot carries
    fifty-six such rows, the earliest four weeks early on a twenty-eight-day
    lead. Flooring them at the project start moved every one of them and the
    chains behind them by exactly that lead. Work that has begun is past the
    project start in the same way: the one in-progress row in the estate
    started five weeks before it, and Project placed its remaining work from
    the actual start. A predecessor that reaches back before the base did not
    hold this activity and is not reported as its driver.

    A relationship becomes the driver when it raises its bound, or when it is
    the first to reach a bound nothing else has claimed. A later tie does not
    displace an earlier claim, so the answer follows declaration order.
    """

    start_bound: int | None = base
    finish_bound: int | None = base
    start_driver: UUID | None = None
    finish_driver: UUID | None = None

    for relationship in incoming:
        predecessor = placed[relationship.predecessor_uid]
        anchor = (
            predecessor.early_finish
            if relationship.anchors_predecessor_finish
            else predecessor.early_start
        )
        calendar = lag_calendar_for(relationship, activity.calendar)
        shifted = shift_lag(calendar, anchor, relationship.lag)
        if shifted is None:
            raise ForwardPassError(
                "SCHEDULE_LAG_UNREACHABLE",
                relationship.uid,
                f"lag {relationship.lag} from {anchor} leaves the calendar",
            )
        if relationship.bounds_successor_start:
            if (
                start_bound is None
                or shifted > start_bound
                or (start_driver is None and shifted == start_bound)
            ):
                start_bound, start_driver = shifted, relationship.uid
        elif (
            finish_bound is None
            or shifted > finish_bound
            or (finish_driver is None and shifted == finish_bound)
        ):
            finish_bound, finish_driver = shifted, relationship.uid

    # With predecessors, one side may have gone unbounded -- every edge bounded
    # the other end. That side is then bounded by the calendar alone, which is
    # the same floor the backward pass uses in the other direction.
    # A bound below the floor is one the calendar overrides: the activity is
    # placed at the floor whether or not the edge exists, so the edge did not
    # drive it. Clearing the driver here is what keeps the replay in
    # :func:`_driver` honest -- a lead that reaches back past the first
    # working moment of the successor's calendar is a bound with no effect.
    # Two different floors, for two different situations.
    #
    # A *start* side no edge reached -- an activity whose predecessors are all
    # FF or SF bounds its finish and says nothing about its start -- takes
    # ``unbounded_floor``, the project start. The calendar's first working
    # moment is not a schedule input: it is wherever the caller chose to
    # compile from, so using it here made such an activity's dates move when
    # the horizon widened while nothing about the schedule changed. The rule
    # is an assumption rather than a measurement; ADR-010's amendment carries
    # it, with what the real schedules say about it.
    #
    # A side an edge *did* reach, below the first moment the calendar has to
    # offer, takes the calendar floor and loses its driver: the activity is
    # placed there whether or not the edge exists, so the edge drove nothing.
    calendar_floor = _calendar_floor(activity)
    if start_bound is None:
        start_bound, start_driver = unbounded_floor, None
    elif start_bound < calendar_floor:
        start_bound, start_driver = calendar_floor, None
    # The finish side takes the calendar's floor when nothing reached it, not
    # the project start: an unbounded finish is already implied by the start
    # bound plus the duration, and flooring it at the project start would drag
    # a lead-placed task back to it -- the fifty-six rows ADR-010 measured.
    if finish_bound is None or finish_bound < calendar_floor:
        finish_bound, finish_driver = calendar_floor, None
    return start_bound, finish_bound, start_driver, finish_driver


def _calendar_floor(activity: PlannedActivity) -> int:
    """Where the calendar begins: the floor for a bound nothing else set."""

    return activity.calendar.first if activity.calendar.first is not None else 0


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
    unbounded_starts: list[UUID] = []
    deferred: list[DeferredConstraint] = []
    violations: list[ConstraintViolation] = []

    for uid in order:
        activity = by_uid[uid]
        state = state_of(activity)
        if state is not ProgressState.NOT_STARTED:
            base = activity.actual_start
        elif incoming[uid]:
            base = None
        else:
            base = network.project_start
        # Whether this activity's predecessors hold it at all is the policy's
        # question, and it has to be asked *before* their bounds are computed.
        # Under progress override an in-progress successor's remaining work
        # runs from the status date and no predecessor holds it -- but the
        # bounds were built first, so a lag that leaves the calendar refused
        # the whole schedule over a coordinate the policy had already
        # discarded. Continuous horizon 0-100, an eighty-unit predecessor, a
        # successor started at ten with one unit left, status date fifty and a
        # thirty-unit lag: both rows fit, and the pass raised
        # ``SCHEDULE_LAG_UNREACHABLE``.
        binding = (
            incoming[uid]
            if relationship_binds(progress_policy, state, network.status_time)
            else ()
        )
        unbounded_floor = base if base is not None else network.project_start
        start_bound, finish_bound, start_driver, finish_driver = _bounds(
            activity, binding, placed, base, unbounded_floor
        )
        # The floor the bounds rested on when no edge reached one end, and so
        # the floor the driver replay must use too.
        floor = base if base is not None else _calendar_floor(activity)
        logic_start, logic_finish = start_bound, finish_bound
        # Whether this row's *start* came from the fallback, decided here,
        # before any constraint is read. Reading it off the row's ``source``
        # afterwards was wrong in both directions: a finish constraint that
        # raises a bound the span already satisfies makes the source say
        # "constraint" without moving the start, and only a constraint that
        # actually takes over the start side displaces the fallback.
        rests_on_fallback = (
            bool(binding)
            and state is ProgressState.NOT_STARTED
            and start_driver is None
            and start_bound == network.project_start
        )

        constraint = activity.constraint_type
        coordinate = activity.constraint_coordinate

        if state is not ProgressState.NOT_STARTED:
            # An actual date is a fact and a constraint is an intention, so
            # reported work is placed on what happened. Every constraint the
            # row carries is recorded as not applied -- not only the types this
            # pass never applies -- so a file that constrains work already
            # under way is never silently scheduled as if it did not.
            if constraint is not ConstraintType.ASAP:
                deferred.append(DeferredConstraint(uid, constraint))
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

        if constraint in DEFERRED_CONSTRAINTS:
            deferred.append(DeferredConstraint(uid, constraint))

        pinned: str | None = None
        constrained = False
        if constraint in DEFERRED_CONSTRAINTS:
            pass
        elif constraint is ConstraintType.SNET and coordinate is not None:
            if coordinate > start_bound:
                start_bound, start_driver, constrained = coordinate, None, True
                # The constraint, not the fallback, decides where it starts.
                rests_on_fallback = False
        elif constraint is ConstraintType.FNET and coordinate is not None:
            if coordinate > finish_bound:
                finish_bound, finish_driver, constrained = coordinate, None, True
        elif constraint is ConstraintType.MSO and coordinate is not None:
            pinned = "start"
            rests_on_fallback = False
        elif constraint is ConstraintType.MFO and coordinate is not None:
            pinned = "finish"
            rests_on_fallback = False

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
                floor,
                network.horizon,
                snap_milestones,
            )
            source = FROM_RELATIONSHIP if driver is not None else FROM_PROJECT_START

        placed[uid] = ActivityTimes(uid, start, finish, driver, source, state)
        if rests_on_fallback:
            # Whether the fallback *decided* anything, not merely whether it
            # supplied the bound: place the activity again with the start
            # bound the calendar alone would give and see whether the answer
            # moves. On the real schedules it does not -- every such row is
            # placed by its own duration against its finish bound -- and a row
            # the fallback really does place reports it.
            elsewhere = _place(
                activity,
                activity.remaining,
                _calendar_floor(activity),
                finish_bound,
                network.horizon,
                snap_milestones,
                pinned,
                coordinate,
            )
            if elsewhere != (start, finish):
                unbounded_starts.append(uid)

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
        network_fingerprint=network.fingerprint(),
        progress_policy=progress_policy,
        unbounded_starts=tuple(unbounded_starts),
        snap_milestones=snap_milestones,
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
    floor: int,
    horizon: int,
    snap_milestones: bool,
) -> UUID | None:
    """Which bound actually placed the activity.

    The finish bound drove only when the start bound alone could not reach it.
    Answered by placing the activity a second time without the finish bound,
    rather than by reasoning about where the calendar's gaps fall. ``floor`` is
    what stands in for the finish bound in that replay: the same floor the
    bounds rested on. For a task with predecessors that is the calendar's
    start, not the project's -- a lead can place such a task before the
    project start, and replaying it against the project start would make a
    finish bound that really moved it look satisfied by the start bound alone.
    """

    if finish_driver is None:
        return start_driver
    # No early return when the start side has no driver of its own. The start
    # bound is still a real coordinate -- the project start, for an activity
    # whose predecessors bound only its finish -- and if the span it produces
    # already satisfies the finish bound then the finish edge moved nothing and
    # did not drive. Crediting it there reported an edge as the reason for a
    # date the schedule would have produced without it.
    # The replay has to place the activity the way :func:`_place` would, not
    # merely find a span: a milestone is a coordinate, and under
    # ``snap_milestones=False`` it sits exactly where its bound puts it, gap or
    # no gap. ``earliest_span`` always snaps a zero-duration span forward, so
    # replaying a milestone through it reported the next working moment and
    # cleared a driver that had really placed the row.
    if duration == 0:
        without_finish: tuple[int, int] | None = None
        moment = max(start_bound, floor)
        if snap_milestones:
            snapped = next_working(activity.calendar, moment)
            moment = snapped if snapped is not None else None
        if moment is not None:
            without_finish = (moment, moment)
    else:
        without_finish = earliest_span(
            activity.calendar, start_bound, floor, duration, horizon
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
    When nothing held the remaining work but the status date, the source says
    so; when nothing held it but the actual start itself, the source is the
    actuals, the same word a complete activity uses.
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
    start_floor = remaining_bound(
        state, progress_policy, start_bound, status_time, activity.actual_start
    )
    finish_floor = remaining_bound(
        state, progress_policy, finish_bound, status_time, activity.actual_start
    )

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
        activity.actual_start,
        network.horizon,
        snap_milestones,
    )
    if driver is not None:
        source = FROM_RELATIONSHIP
    elif status_time is not None and status_time >= activity.actual_start:
        source = FROM_STATUS_TIME
    else:
        source = FROM_ACTUALS
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
                [
                    str(row.uid),
                    row.early_start,
                    row.early_finish,
                    row.remaining_start,
                    row.state.value,
                ]
                for row in times
            ),
        }
    )
