"""The network a forward pass consumes: activities, precedence, and their calendars.

Deliberately not the canonical model. The engine is handed integer coordinates
and :class:`~sto.core.calendar.arithmetic.CompiledIntervals` and nothing else,
so the same pass runs over a real schedule compiled to seconds from an epoch and
over a conformance case declared in hours from an origin without either knowing
about the other. **Whatever unit the caller compiled its calendars in is the
unit of every number here**, and the engine never converts one to another.

Building a network from a canonical :class:`~sto.core.model.entities.Schedule`
-- resolving which calendar an activity inherits, and which calendar a lag is
consumed on -- is :mod:`sto.core.engine.plan`. That is where policy lives; this
module holds no policy at all.

Every refusal is a code, never a guess, in the manner of
:class:`~sto.core.calendar.compile.CalendarCompileError`:

``SCHEDULE_HORIZON_INVALID``
    The horizon does not lie after the project start.
``SCHEDULE_DUPLICATE_ACTIVITY`` / ``SCHEDULE_DUPLICATE_RELATIONSHIP``
    Two rows claim one identity.
``SCHEDULE_UNKNOWN_ACTIVITY``
    A relationship names an activity the network does not carry.
``SCHEDULE_SELF_RELATIONSHIP``
    An activity is its own predecessor.
``SCHEDULE_DURATION_NEGATIVE``
    A duration below zero, which has no forward meaning.
``SCHEDULE_CALENDAR_EMPTY``
    An activity whose calendar has no working time in the horizon.
``SCHEDULE_CONSTRAINT_INCOMPLETE``
    A dated constraint type without its date.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sto.core.calendar.arithmetic import CompiledIntervals, add_working, sub_working
from sto.core.model.enums import ConstraintType, RelationshipType

#: Constraints the forward pass acts on. SNET and FNET raise a bound; MSO and
#: MFO pin a coordinate and are allowed to override precedence, which is what
#: makes them hard in the canonical model.
FORWARD_CONSTRAINTS = frozenset(
    {
        ConstraintType.SNET,
        ConstraintType.FNET,
        ConstraintType.MSO,
        ConstraintType.MFO,
    }
)

#: Constraints that are recognised and carried, but cannot move an early date.
#: A late constraint does not pull a forward pass earlier -- it produces
#: negative float in the backward pass, which is where SNLT and FNLT are
#: applied. ALAP is answered by neither pass: it moves where an activity sits,
#: not only how much slack it has, and is carried through both rather than
#: guessed at. Reporting them here is what stops a file that carries one from
#: being silently treated as ASAP.
DEFERRED_CONSTRAINTS = frozenset(
    {
        ConstraintType.ALAP,
        ConstraintType.SNLT,
        ConstraintType.FNLT,
    }
)

#: Constraints the backward pass acts on. SNLT and FNLT lower a late date --
#: which is how a late constraint produces negative float rather than pulling an
#: early date earlier -- and MSO and MFO pin the late coordinate to the same
#: place they pinned the early one, so a hard-constrained activity has no float.
#: ALAP is in neither set: it changes where an activity is *placed*, not only
#: how much slack it has, so a backward pass cannot answer it and says so.
BACKWARD_CONSTRAINTS = frozenset(
    {
        ConstraintType.SNLT,
        ConstraintType.FNLT,
        ConstraintType.MSO,
        ConstraintType.MFO,
    }
)

#: The dated constraints: meaningless without a coordinate.
_DATED_CONSTRAINTS = FORWARD_CONSTRAINTS | {ConstraintType.SNLT, ConstraintType.FNLT}


class NetworkError(ValueError):
    """A network that cannot be scheduled, and why, by code."""

    def __init__(self, code: str, uid: UUID | None = None, detail: str = "") -> None:
        self.code = code
        self.uid = uid
        self.detail = detail
        super().__init__(f"{code} {uid}{': ' + detail if detail else ''}")


class ForwardPassError(NetworkError):
    """A network that cannot be scheduled forward."""


class BackwardPassError(NetworkError):
    """A network that cannot be scheduled backward.

    Separate from :class:`ForwardPassError` because the two passes fail for
    different reasons on the same network: a forward pass runs out of horizon,
    a backward pass runs out of floor, and a caller that catches one should not
    silently swallow the other.
    """


@dataclass(frozen=True, slots=True)
class PlannedActivity:
    """One activity as the engine sees it.

    ``duration`` is productive time consumed on ``calendar``, so a milestone is
    simply a duration of zero. ``calendar`` is already the intersection of
    whatever calendars apply -- the engine does not intersect anything.
    """

    uid: UUID
    duration: int
    calendar: CompiledIntervals
    constraint_type: ConstraintType = ConstraintType.ASAP
    constraint_coordinate: int | None = None

    @property
    def is_milestone(self) -> bool:
        return self.duration == 0


@dataclass(frozen=True, slots=True)
class PlannedRelationship:
    """One precedence edge with its signed lag.

    ``lag_calendar`` of ``None`` means the successor's own calendar, which is
    both the canonical model's default policy for Microsoft files and what the
    conformance corpus declares when it writes ``lag_calendar: null``. Anything
    else -- the predecessor's calendar, the project calendar, or a continuous
    calendar for elapsed lag -- is resolved before it reaches here.
    """

    uid: UUID
    predecessor_uid: UUID
    successor_uid: UUID
    type: RelationshipType = RelationshipType.FS
    lag: int = 0
    lag_calendar: CompiledIntervals | None = None

    @property
    def anchors_predecessor_finish(self) -> bool:
        """FS and FF hang off the predecessor's finish; SS and SF off its start."""

        return self.type in (RelationshipType.FS, RelationshipType.FF)

    @property
    def bounds_successor_start(self) -> bool:
        """FS and SS bound the successor's start; FF and SF bound its finish."""

        return self.type in (RelationshipType.FS, RelationshipType.SS)


@dataclass(frozen=True, slots=True)
class Network:
    """Activities, edges, and the window they are scheduled in.

    ``project_start`` is the earliest coordinate any activity may occupy and
    ``horizon`` the last; both are in the calendars' own unit. Running past the
    horizon is a refusal, never a wrapped or guessed answer.
    """

    activities: tuple[PlannedActivity, ...]
    relationships: tuple[PlannedRelationship, ...] = ()
    project_start: int = 0
    horizon: int = 0

    def activity_by_uid(self) -> dict[UUID, PlannedActivity]:
        return {activity.uid: activity for activity in self.activities}

    def predecessors(self) -> dict[UUID, tuple[PlannedRelationship, ...]]:
        """Incoming edges per activity, in declaration order."""

        edges: dict[UUID, list[PlannedRelationship]] = {a.uid: [] for a in self.activities}
        for relationship in self.relationships:
            edges[relationship.successor_uid].append(relationship)
        return {uid: tuple(rows) for uid, rows in edges.items()}

    def successors(self) -> dict[UUID, tuple[PlannedRelationship, ...]]:
        """Outgoing edges per activity, in declaration order."""

        edges: dict[UUID, list[PlannedRelationship]] = {a.uid: [] for a in self.activities}
        for relationship in self.relationships:
            edges[relationship.predecessor_uid].append(relationship)
        return {uid: tuple(rows) for uid, rows in edges.items()}

    def validate(self) -> None:
        """Refuse a network the forward pass could only guess at.

        Everything checked here is a property of the network alone, so it is
        checked once, before any coordinate is computed, and reported against
        the row that carries it.
        """

        if self.horizon <= self.project_start:
            raise ForwardPassError(
                "SCHEDULE_HORIZON_INVALID",
                None,
                f"horizon {self.horizon} does not follow project start {self.project_start}",
            )

        seen: set[UUID] = set()
        for activity in self.activities:
            if activity.uid in seen:
                raise ForwardPassError("SCHEDULE_DUPLICATE_ACTIVITY", activity.uid)
            seen.add(activity.uid)
            if activity.duration < 0:
                raise ForwardPassError(
                    "SCHEDULE_DURATION_NEGATIVE", activity.uid, str(activity.duration)
                )
            if not activity.calendar.intervals:
                raise ForwardPassError("SCHEDULE_CALENDAR_EMPTY", activity.uid)
            if (
                activity.constraint_type in _DATED_CONSTRAINTS
                and activity.constraint_coordinate is None
            ):
                raise ForwardPassError(
                    "SCHEDULE_CONSTRAINT_INCOMPLETE",
                    activity.uid,
                    activity.constraint_type.value,
                )

        edges: set[UUID] = set()
        for relationship in self.relationships:
            if relationship.uid in edges:
                raise ForwardPassError("SCHEDULE_DUPLICATE_RELATIONSHIP", relationship.uid)
            edges.add(relationship.uid)
            for endpoint in (relationship.predecessor_uid, relationship.successor_uid):
                if endpoint not in seen:
                    raise ForwardPassError(
                        "SCHEDULE_UNKNOWN_ACTIVITY", relationship.uid, str(endpoint)
                    )
            if relationship.predecessor_uid == relationship.successor_uid:
                raise ForwardPassError("SCHEDULE_SELF_RELATIONSHIP", relationship.uid)


def shift_lag(calendar: CompiledIntervals, anchor: int, lag: int) -> int | None:
    """Signed productive lag forward from ``anchor``; zero keeps the exact coordinate.

    Equal to :func:`~sto.core.calendar.arithmetic.shift_working_time` on every
    input, which the calendar slice proved over ten thousand random trials in
    each direction. **Zero returns the anchor untouched even when it lies in a
    gap**: snapping is a property of placement, and doing it here as well moves
    an activity a whole interval too far.
    """

    if lag == 0:
        return anchor
    if lag > 0:
        return add_working(calendar, anchor, lag)
    return sub_working(calendar, anchor, -lag)


def unshift_lag(calendar: CompiledIntervals, anchor: int, lag: int) -> int | None:
    """Signed productive lag backward from ``anchor``: the inverse of :func:`shift_lag`.

    A positive lag that pushed a successor forward pulls its predecessor back by
    the same productive amount, and a negative lag does the reverse.
    """

    if lag == 0:
        return anchor
    if lag > 0:
        return sub_working(calendar, anchor, lag)
    return add_working(calendar, anchor, -lag)
