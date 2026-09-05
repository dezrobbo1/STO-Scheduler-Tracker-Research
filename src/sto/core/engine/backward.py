"""The backward pass: latest start and finish over all four relationship types.

One traversal in reverse topological order, and the mirror of
:mod:`sto.core.engine.forward` line for line. Each activity takes an upper bound
on its start and an upper bound on its finish from its successors, is lowered by
a constraint, and is then placed at the latest span its own calendar allows.

The four types read the opposite end from the one they read going forward, and
bound the opposite end of the opposite activity:

=====  ==========================  =========================
Type   reads the successor's       bounds the predecessor's
=====  ==========================  =========================
FS     late start                  finish
SS     late start                  start
FF     late finish                 finish
SF     late finish                 start
=====  ==========================  =========================

which is the forward table with both columns transposed, so the same two
properties on :class:`~sto.core.engine.network.PlannedRelationship` answer it --
``bounds_successor_start`` says which end of the successor is read and
``anchors_predecessor_finish`` says which end of the predecessor is bounded.
Lag is subtracted where the forward pass adds it, on the same lag calendar, and
**zero lag again returns the anchor untouched**: snapping belongs to placement
in this direction too.

Placement is :func:`~sto.core.calendar.arithmetic.latest_span`, the mirror of
the forward pass's ``earliest_span``, and milestones read the same
:class:`~sto.core.model.enums.MilestoneSnapPolicy` rather than picking a rule.

An activity with no successors is bounded by the project's late finish, which
defaults to the forward pass's project finish -- the convention that makes the
longest path's total float zero. A caller with a contractual end date passes it
instead, and every activity's float moves by the difference.

**A required finish earlier than the computed one, or a late constraint that
cannot be met, produces negative float rather than a refusal -- but only as far
down as the calendar was compiled.** Late dates then run before the project
start, and a window that begins at the project start has no room to put them in.
There is no coordinate to return, so that is a refusal naming the window rather
than a guess; :func:`~sto.core.engine.plan.build_plan` says what the horizon has
to allow for.

Constraints. SNLT and FNLT lower a late date, which is exactly how a late
constraint earns negative float rather than dragging an early date backwards;
the forward pass promised this and carried them here. MSO and MFO pin the late
coordinate to the same place they pinned the early one, so a hard-constrained
activity has no float in either direction. ALAP is answered by neither pass --
it changes where an activity is placed, not only its slack -- so it is carried
through to :attr:`BackwardPass.deferred_constraints` exactly as the forward pass
carried it here, and is not silently treated as ASAP.

What this pass does not do: no float and no criticality, which are arithmetic
over this pass and the forward one and live in
:mod:`sto.core.engine.criticality`; no progress or status date; no rollup.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sto.core.calendar.arithmetic import (
    CompiledIntervals,
    add_working,
    latest_span,
    prev_working_start,
    sub_working,
)
from sto.core.hashing import canonical_sha256
from sto.core.model.enums import ConstraintType

from .forward import ForwardPass
from .network import (
    BackwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    unshift_lag,
)

#: Why an activity's late span sits where it does. The mirror of the forward
#: pass's sources, and deliberately the same strings for the two that coincide.
FROM_PROJECT_FINISH = "project_finish"
FROM_RELATIONSHIP = "relationship"
FROM_CONSTRAINT = "constraint"

#: Named on the fingerprint so a stored answer says which pass produced it.
BACKWARD_PASS_PROFILE = "sto-backward-pass-v1"


@dataclass(frozen=True, slots=True)
class ActivityLateTimes:
    """One activity's latest span and what held it there."""

    uid: UUID
    late_start: int
    late_finish: int
    driving_relationship_uid: UUID | None = None
    source: str = FROM_PROJECT_FINISH


@dataclass(frozen=True, slots=True)
class DeferredLateConstraint:
    """A constraint recognised, carried, and deliberately not applied here."""

    activity_uid: UUID
    type: ConstraintType


@dataclass(frozen=True, slots=True)
class BackwardPass:
    """Latest dates for every activity, and the evidence for them."""

    times: tuple[ActivityLateTimes, ...]
    #: The forward pass's topological order, so ``order[i]`` is ``times[i].uid``
    #: exactly as it is on :class:`~sto.core.engine.forward.ForwardPass` and the
    #: two passes' rows line up. The traversal ran the other way --
    #: :meth:`traversal_order` is that -- but a result whose two tuples disagreed
    #: about their order would make ``zip(order, times)`` quietly wrong on one
    #: class and right on the other.
    order: tuple[UUID, ...]
    project_late_finish: int
    deferred_constraints: tuple[DeferredLateConstraint, ...] = ()
    fingerprint: str = ""

    def by_uid(self) -> dict[UUID, ActivityLateTimes]:
        return {row.uid: row for row in self.times}

    def traversal_order(self) -> tuple[UUID, ...]:
        """The order the pass actually visited activities in: reverse topological."""

        return tuple(reversed(self.order))

    def driving_relationships(self) -> tuple[UUID, ...]:
        """Every relationship that held an activity back, in :attr:`order`."""

        seen: list[UUID] = []
        for row in self.times:
            uid = row.driving_relationship_uid
            if uid is not None and uid not in seen:
                seen.append(uid)
        return tuple(seen)


def _bounds(
    activity: PlannedActivity,
    outgoing: tuple[PlannedRelationship, ...],
    placed: dict[UUID, ActivityLateTimes],
    project_late_finish: int,
    calendars: dict[UUID, CompiledIntervals],
) -> tuple[int, int, UUID | None, UUID | None]:
    """Upper bounds on start and finish from precedence, and what drove each.

    A relationship becomes the driver when it lowers its bound, or when it is
    the first to reach a bound nothing else has claimed -- the mirror of the
    forward pass's rule, so a later tie does not displace an earlier claim and
    the answer follows declaration order in this direction too.

    The lag calendar is resolved exactly as the forward pass resolved it: a
    relationship carrying no explicit lag calendar is consumed on **the
    successor's** own calendar, which here is the other endpoint's rather than
    this activity's. Reading it off this activity instead would make one lag
    mean two different amounts of work depending on the direction of travel.
    """

    start_bound = project_late_finish
    finish_bound = project_late_finish
    start_driver: UUID | None = None
    finish_driver: UUID | None = None

    for relationship in outgoing:
        successor = placed[relationship.successor_uid]
        anchor = (
            successor.late_start
            if relationship.bounds_successor_start
            else successor.late_finish
        )
        calendar = (
            relationship.lag_calendar
            if relationship.lag_calendar is not None
            else calendars[relationship.successor_uid]
        )
        shifted = unshift_lag(calendar, anchor, relationship.lag)
        if shifted is None:
            raise BackwardPassError(
                "SCHEDULE_LAG_UNREACHABLE",
                relationship.uid,
                f"lag {relationship.lag} back from {anchor} leaves the calendar",
            )
        if relationship.anchors_predecessor_finish:
            if shifted < finish_bound or (finish_driver is None and shifted == finish_bound):
                finish_bound, finish_driver = shifted, relationship.uid
        elif shifted < start_bound or (start_driver is None and shifted == start_bound):
            start_bound, start_driver = shifted, relationship.uid

    return start_bound, finish_bound, start_driver, finish_driver


def backward_pass(
    network: Network,
    forward: ForwardPass,
    *,
    snap_milestones: bool = False,
    project_late_finish: int | None = None,
) -> BackwardPass:
    """Latest start and finish for every activity in ``network``.

    ``forward`` supplies the traversal order -- reversed here, so the two passes
    cannot disagree about the topology -- and the default project late finish.
    ``project_late_finish`` overrides that with a required end date, which moves
    every activity's float by the difference and is the only way a schedule
    reports float against a contractual date rather than against itself.
    """

    network.validate()
    if set(forward.order) != {activity.uid for activity in network.activities}:
        raise BackwardPassError(
            "SCHEDULE_PASS_MISMATCH",
            None,
            "the forward pass covers a different set of activities",
        )

    by_uid = network.activity_by_uid()
    outgoing = network.successors()
    late_finish = (
        forward.project_finish if project_late_finish is None else project_late_finish
    )
    calendars = {activity.uid: activity.calendar for activity in network.activities}

    placed: dict[UUID, ActivityLateTimes] = {}
    deferred: list[DeferredLateConstraint] = []

    for uid in reversed(forward.order):
        activity = by_uid[uid]
        start_bound, finish_bound, start_driver, finish_driver = _bounds(
            activity, outgoing[uid], placed, late_finish, calendars
        )

        constraint = activity.constraint_type
        coordinate = activity.constraint_coordinate
        pinned: str | None = None
        constrained = False
        if constraint is ConstraintType.ALAP:
            deferred.append(DeferredLateConstraint(uid, constraint))
        elif constraint is ConstraintType.SNLT and coordinate is not None:
            if coordinate < start_bound:
                start_bound, start_driver, constrained = coordinate, None, True
        elif constraint is ConstraintType.FNLT and coordinate is not None:
            if coordinate < finish_bound:
                finish_bound, finish_driver, constrained = coordinate, None, True
        elif constraint is ConstraintType.MSO and coordinate is not None:
            pinned = "start"
        elif constraint is ConstraintType.MFO and coordinate is not None:
            pinned = "finish"

        start, finish = _place(
            activity,
            start_bound,
            finish_bound,
            snap_milestones,
            pinned,
            coordinate,
        )

        driver: UUID | None
        if pinned is not None or constrained:
            source, driver = FROM_CONSTRAINT, None
        else:
            driver = _driver(
                activity,
                start_bound,
                finish_bound,
                start_driver,
                finish_driver,
                late_finish,
            )
            source = FROM_RELATIONSHIP if driver is not None else FROM_PROJECT_FINISH

        placed[uid] = ActivityLateTimes(uid, start, finish, driver, source)

    times = tuple(placed[uid] for uid in forward.order)
    return BackwardPass(
        times=times,
        order=forward.order,
        project_late_finish=late_finish,
        deferred_constraints=tuple(deferred),
        fingerprint=_fingerprint(times, late_finish),
    )


def _place(
    activity: PlannedActivity,
    start_bound: int,
    finish_bound: int,
    snap_milestones: bool,
    pinned: str | None,
    coordinate: int | None,
) -> tuple[int, int]:
    """The activity's latest span, or a refusal when the calendar runs out beneath it.

    The floor is where the **calendar** ends, not where the project starts. A
    late date before the project start is not an error: it is what an
    over-committed schedule looks like, and the negative float it produces is
    the report.

    That report is only as deep as the compiled window, though, and this is the
    one place where the mirror is not symmetric. The forward pass running out of
    horizon means the schedule genuinely does not fit; the backward pass running
    out of calendar means *we did not compile enough of it*, because there is no
    coordinate below the window to name. So the refusal says where the window
    starts, and :func:`~sto.core.engine.plan.build_plan` documents that the
    horizon's lower end is what bounds how much negative float can be expressed.
    """

    calendar = activity.calendar
    floor = calendar.first if calendar.first is not None else 0

    if pinned is not None:
        if coordinate is None:
            raise BackwardPassError(
                "SCHEDULE_CONSTRAINT_INCOMPLETE",
                activity.uid,
                activity.constraint_type.value,
            )
        if pinned == "start":
            finish = (
                coordinate
                if activity.is_milestone
                else add_working(calendar, coordinate, activity.duration)
            )
            if finish is None or coordinate < floor:
                raise BackwardPassError(
                    "SCHEDULE_FLOOR_EXCEEDED", activity.uid, "must start on"
                )
            return coordinate, finish
        start = (
            coordinate
            if activity.is_milestone
            else sub_working(calendar, coordinate, activity.duration)
        )
        if start is None or start < floor:
            raise BackwardPassError(
                "SCHEDULE_FLOOR_EXCEEDED", activity.uid, "must finish on"
            )
        return start, coordinate

    if activity.is_milestone:
        moment = min(start_bound, finish_bound)
        if snap_milestones:
            # A milestone is a coordinate that work starts at, not one work
            # ends at, so it takes the start-side answer -- the mirror of the
            # forward pass's ``next_working``, not ``prev_working``.
            snapped = prev_working_start(calendar, moment)
            if snapped is None:
                raise BackwardPassError(
                    "SCHEDULE_FLOOR_EXCEEDED", activity.uid, "milestone snap"
                )
            moment = snapped
        if moment < floor:
            raise BackwardPassError("SCHEDULE_FLOOR_EXCEEDED", activity.uid, "milestone")
        return moment, moment

    span = latest_span(calendar, start_bound, finish_bound, activity.duration, floor)
    if span is None:
        raise BackwardPassError(
            "SCHEDULE_FLOOR_EXCEEDED",
            activity.uid,
            f"duration {activity.duration} back from {finish_bound} needs working time "
            f"below the compiled window, which starts at {floor}; widen the horizon "
            f"to express float this negative",
        )
    return span


def _driver(
    activity: PlannedActivity,
    start_bound: int,
    finish_bound: int,
    start_driver: UUID | None,
    finish_driver: UUID | None,
    project_late_finish: int,
) -> UUID | None:
    """Which bound actually held the activity back.

    The start bound held it only when the finish bound alone could not reach
    back that far. Answered by placing the activity a second time without the
    start bound, exactly as the forward pass answers the mirror question, rather
    than by reasoning about where the calendar's gaps fall.
    """

    if start_driver is None:
        return finish_driver
    if finish_driver is None:
        return start_driver
    floor = activity.calendar.first if activity.calendar.first is not None else 0
    without_start = latest_span(
        activity.calendar, project_late_finish, finish_bound, activity.duration, floor
    )
    if without_start is not None and without_start[0] <= start_bound:
        return finish_driver
    return start_driver


def _fingerprint(times: tuple[ActivityLateTimes, ...], project_late_finish: int) -> str:
    """A hash of the answer, so two runs are compared without comparing objects."""

    return canonical_sha256(
        {
            "profile": BACKWARD_PASS_PROFILE,
            "project_late_finish": project_late_finish,
            "times": sorted(
                [str(row.uid), row.late_start, row.late_finish] for row in times
            ),
        }
    )
