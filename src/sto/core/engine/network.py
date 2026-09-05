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
``SCHEDULE_ACTUAL_FINISH_WITHOUT_START``
    An activity that finished without ever starting.
``SCHEDULE_ACTUALS_INVERTED``
    An actual finish before its own actual start.
``SCHEDULE_REMAINING_NEGATIVE``
    A remaining duration below zero, which has no forward meaning.
``SCHEDULE_REMAINING_UNKNOWN``
    Work that has started with no remaining duration reported. An untouched
    activity has all of its duration left; one under way may have consumed any
    part of it, and scheduling the whole duration again would invent a
    forecast. Every real file and every corpus case that reports a start
    reports what is left, so the case is refused rather than guessed.
``SCHEDULE_PASS_MISMATCH``
    A forward pass handed to the backward pass or the float was computed over
    a different network -- bound by :meth:`Network.fingerprint`.
``SCHEDULE_STATUS_TIME_INVALID``
    A status time outside the window the network is scheduled in.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sto.core.calendar.arithmetic import CompiledIntervals, add_working, sub_working
from sto.core.hashing import canonical_sha256
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

    The three progress fields are **facts read off the source**, not policy.
    ``actual_start`` and ``actual_finish`` are coordinates the work is reported
    to have happened at, and ``remaining_duration`` is the productive time the
    work is reported to have left. What those facts then *do* to the schedule --
    whether an unfinished successor's remaining work waits for its predecessor
    or continues from the status date -- is a policy question, and it lives in
    :mod:`sto.core.engine.progress` with the rest of the policy, not here.

    ``remaining_duration`` of ``None`` means the source said nothing, which is
    not the same as saying zero: an activity nobody has touched has all of its
    duration left, and :meth:`remaining` is where that default is applied once.
    For work that has started the default would be a guess, so
    :meth:`Network.validate` refuses it (``SCHEDULE_REMAINING_UNKNOWN``).
    """

    uid: UUID
    duration: int
    calendar: CompiledIntervals
    constraint_type: ConstraintType = ConstraintType.ASAP
    constraint_coordinate: int | None = None
    actual_start: int | None = None
    actual_finish: int | None = None
    remaining_duration: int | None = None
    #: The calendar a *float* on this activity is measured in, when it is not
    #: the one the work is placed on. Microsoft Project places work on the
    #: resource's calendar and measures slack on the task's own or the
    #: project's -- the same calendar it consumes a lag on -- and the two are
    #: routinely different shifts. ``None`` means the scheduling calendar, which
    #: is what the corpus declares and what an activity with no resource has.
    measure_calendar: CompiledIntervals | None = None

    @property
    def float_calendar(self) -> CompiledIntervals:
        """The calendar a float on this activity is measured in."""

        return self.calendar if self.measure_calendar is None else self.measure_calendar

    @property
    def is_milestone(self) -> bool:
        return self.duration == 0

    @property
    def has_started(self) -> bool:
        """The source reports work began. A fact, not a status-date comparison."""

        return self.actual_start is not None

    @property
    def is_complete(self) -> bool:
        """The source reports work finished."""

        return self.actual_finish is not None

    @property
    def remaining(self) -> int:
        """Productive time left, defaulting to the whole duration when unsaid.

        A complete activity has none left whatever the source wrote, which is
        the one place this property is more than a default: a file that reports
        a finish date and a non-zero remaining duration is reporting two
        different things, and the finish date is the one that happened.
        """

        if self.is_complete:
            return 0
        if self.remaining_duration is None:
            return self.duration
        return self.remaining_duration


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

    ``status_time`` is the coordinate progress is reported as at -- Microsoft
    Project's ``StatusDate`` and Primavera's data date -- and is the line
    remaining work is scheduled from. ``None`` means the source declared none,
    and a schedule with no status time is scheduled exactly as it was before
    this slice: the passes never invent one, because a status time nobody
    declared would silently move every unfinished activity.
    """

    activities: tuple[PlannedActivity, ...]
    relationships: tuple[PlannedRelationship, ...] = ()
    project_start: int = 0
    horizon: int = 0
    status_time: int | None = None

    @property
    def is_progressed(self) -> bool:
        """Any activity carries an actual date. Progress, not merely a status date."""

        return any(a.has_started or a.is_complete for a in self.activities)

    def activity_by_uid(self) -> dict[UUID, PlannedActivity]:
        return {activity.uid: activity for activity in self.activities}

    def fingerprint(self) -> str:
        """A hash of every input the passes read.

        A pass result carries this so that the backward pass and the float can
        refuse a forward pass computed over some other network -- one that
        happens to share every activity identity with this one but not its
        durations, calendars or edges. Calendars are hashed by content, once
        per distinct interval set, so the cost is the number of calendars and
        not the number of activities that share them.
        """

        digests: dict[tuple, str] = {}

        def calendar_digest(calendar: CompiledIntervals | None) -> str | None:
            if calendar is None:
                return None
            key = calendar.intervals
            if key not in digests:
                digests[key] = canonical_sha256([list(pair) for pair in key])
            return digests[key]

        return canonical_sha256(
            {
                "project_start": self.project_start,
                "horizon": self.horizon,
                "status_time": self.status_time,
                "activities": [
                    [
                        str(a.uid),
                        a.duration,
                        calendar_digest(a.calendar),
                        a.constraint_type.value,
                        a.constraint_coordinate,
                        a.actual_start,
                        a.actual_finish,
                        a.remaining_duration,
                        calendar_digest(a.measure_calendar),
                    ]
                    for a in self.activities
                ],
                "relationships": [
                    [
                        str(r.uid),
                        str(r.predecessor_uid),
                        str(r.successor_uid),
                        r.type.value,
                        r.lag,
                        calendar_digest(r.lag_calendar),
                    ]
                    for r in self.relationships
                ],
            }
        )

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

        if self.status_time is not None and not (
            self.project_start <= self.status_time <= self.horizon
        ):
            raise ForwardPassError(
                "SCHEDULE_STATUS_TIME_INVALID",
                None,
                f"status time {self.status_time} is outside "
                f"[{self.project_start}, {self.horizon}]",
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
            if activity.remaining_duration is not None and activity.remaining_duration < 0:
                raise ForwardPassError(
                    "SCHEDULE_REMAINING_NEGATIVE",
                    activity.uid,
                    str(activity.remaining_duration),
                )
            if activity.actual_finish is not None and activity.actual_start is None:
                raise ForwardPassError(
                    "SCHEDULE_ACTUAL_FINISH_WITHOUT_START", activity.uid
                )
            if (
                activity.has_started
                and not activity.is_complete
                and activity.remaining_duration is None
            ):
                raise ForwardPassError(
                    "SCHEDULE_REMAINING_UNKNOWN",
                    activity.uid,
                    "work has started and the source does not say what is left",
                )
            if (
                activity.actual_start is not None
                and activity.actual_finish is not None
                and activity.actual_finish < activity.actual_start
            ):
                raise ForwardPassError(
                    "SCHEDULE_ACTUALS_INVERTED",
                    activity.uid,
                    f"finish {activity.actual_finish} before start {activity.actual_start}",
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
