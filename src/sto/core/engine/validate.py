"""An independent check on a finished result (slice S6).

Every other test in this package asks the engine to compute something and
compares the answer with an expected one. This module asks a different
question: given a result the engine has already produced, do the relations it
*claims* actually hold?

The distinction is the whole point. A defect in the forward pass shows up in
the forward pass's own answer and in anything that recomputes the answer the
same way -- which is how a suite that passed in full sat above a
free float that overstated safe delay across calendars, a lag inverse that
landed after its own bound, and a constraint one pass applied while the other
set it aside. Each was found by reading the code rather than by running it.

So nothing here calls :func:`~sto.core.engine.network.shift_lag`,
``earliest_span``, or any of the three passes. It reads dates, durations and
calendars, and counts working time between coordinates with
:func:`~sto.core.calendar.arithmetic.working_between` -- one function, whose
own agreement with the reference implementation the calendar slice established
over ten thousand random inputs. If the passes and this module agree, they
agree by two different routes.

What it cannot check is what the file says: this is a consistency check, not
an oracle. A schedule can be internally perfect and still disagree with
Microsoft Project, which is what the real-file comparisons are for.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sto.core.calendar.arithmetic import working_between
from sto.core.model.enums import ConstraintType, ProgressPolicy

#: Constraints this check does not ask about: ASAP places nothing, and ALAP is
#: carried through the passes rather than applied to an early date.
_UNCHECKED_CONSTRAINTS = frozenset({ConstraintType.ASAP, ConstraintType.ALAP})

from .backward import BackwardPass
from .criticality import FloatAnalysis
from .forward import ForwardPass
from .network import Network
from .progress import ProgressState, relationship_binds, state_of

__all__ = ["VALIDATOR_PROFILE", "Violation", "validate_result"]

#: Named on a report so a stored one says which rules were applied.
VALIDATOR_PROFILE = "sto-validator-v1"


@dataclass(frozen=True, slots=True)
class Violation:
    """A relation the result claims that its own dates do not support."""

    code: str
    uid: UUID | None
    detail: str = ""


def validate_result(
    network: Network,
    forward: ForwardPass,
    backward: BackwardPass,
    floats: FloatAnalysis,
    *,
    threshold: int | None = None,
    progress_policy: ProgressPolicy = ProgressPolicy.RETAINED_LOGIC,
    elapsed: frozenset[UUID] = frozenset(),
) -> tuple[Violation, ...]:
    """Check a finished result against itself, and report what does not hold.

    ``elapsed`` names activities whose span is wall-clock rather than working
    time. They are placed on a continuous calendar, so the span check below
    holds for them too, but the caller knows which they are and saying so keeps
    the rule visible rather than implied.

    ``threshold`` defaults to the one the float analysis recorded, because that
    is the threshold its own flags were computed under; passing a different one
    asks a different question and is allowed, but defaulting to zero made the
    validator disagree with every sound result on a file that declares a
    threshold, which CALCINER does.

    An empty tuple is the answer for a sound result. Violations carry a code so
    a caller can act on the class rather than parse prose.
    """

    if threshold is None:
        threshold = floats.threshold
    violations: list[Violation] = []
    early = forward.by_uid()
    late = backward.by_uid()
    slack = floats.by_uid()
    activities = {activity.uid: activity for activity in network.activities}
    states = {uid: state_of(activity) for uid, activity in activities.items()}

    # --- every row is answered exactly once, by all three ---------------
    # Counted on the tuples the passes returned, not on the maps: ``by_uid``
    # collapses a duplicated row silently, so a result carrying one twice
    # would have satisfied an "exactly once" check built from the map.
    for name, rows in (
        ("FORWARD", [row.uid for row in forward.times]),
        ("BACKWARD", [row.uid for row in backward.times]),
        ("FLOAT", [row.uid for row in floats.rows]),
    ):
        for uid, count in Counter(rows).items():
            if count > 1:
                violations.append(Violation(f"{name}_DUPLICATE_ACTIVITY", uid, f"{count} rows"))
    for name, answered in (
        ("FORWARD", set(early)),
        ("BACKWARD", set(late)),
        ("FLOAT", set(slack)),
    ):
        missing = set(activities) - answered
        for uid in sorted(missing, key=str):
            violations.append(Violation(f"{name}_MISSING_ACTIVITY", uid))
        for uid in sorted(answered - set(activities), key=str):
            violations.append(Violation(f"{name}_UNKNOWN_ACTIVITY", uid))

    for uid, activity in activities.items():
        row = early.get(uid)
        late_row = late.get(uid)
        if row is None or late_row is None:
            continue
        state = states[uid]

        # --- a span is ordered, and consumes the work it says it does ----
        if row.early_finish < row.early_start:
            violations.append(
                Violation("EARLY_SPAN_INVERTED", uid, f"{row.early_start} > {row.early_finish}")
            )
        if late_row.late_finish < late_row.late_start:
            violations.append(
                Violation(
                    "LATE_SPAN_INVERTED", uid, f"{late_row.late_start} > {late_row.late_finish}"
                )
            )

        # Only the *duration* checks are exempt for completed work: its
        # reported dates are facts and consume whatever they consume. Its
        # float, its criticality and the order of its spans are still claims
        # this result makes, and skipping the whole row let a completed
        # activity be marked critical with arbitrary float and pass.
        if state is not ProgressState.COMPLETE:
            expected = activity.remaining
            begins = row.remaining_start if row.remaining_start is not None else row.early_start
            consumed = working_between(activity.calendar, begins, row.early_finish)
            if consumed != expected:
                violations.append(
                    Violation(
                        "EARLY_SPAN_WRONG_LENGTH",
                        uid,
                        f"consumes {consumed}, duration {expected}",
                    )
                )
            late_consumed = working_between(
                activity.calendar, late_row.late_start, late_row.late_finish
            )
            if late_consumed != expected:
                violations.append(
                    Violation(
                        "LATE_SPAN_WRONG_LENGTH",
                        uid,
                        f"consumes {late_consumed}, duration {expected}",
                    )
                )

            # --- remaining work obeys the floor the policy gives it -------
            if state is ProgressState.IN_PROGRESS and row.remaining_start is not None:
                floor = activity.actual_start
                if (
                    network.status_time is not None
                    and progress_policy is ProgressPolicy.PROGRESS_OVERRIDE
                    and floor is not None
                ):
                    floor = max(floor, network.status_time)
                if floor is not None and row.remaining_start < floor:
                    violations.append(
                        Violation(
                            "REMAINING_START_BEFORE_ITS_FLOOR",
                            uid,
                            f"remaining start {row.remaining_start} < {floor}",
                        )
                    )

        # --- the late span is not earlier than the early one -------------
        # Measured against the *remaining* start where there is one: for work
        # under way the early start is the immovable actual one while the late
        # dates describe the part that can still move, so comparing those two
        # accepted a late span earlier than the remaining span it bounds.
        early_side = row.remaining_start if row.remaining_start is not None else row.early_start
        if late_row.late_start < early_side:
            violations.append(
                Violation(
                    "LATE_BEFORE_EARLY",
                    uid,
                    f"late start {late_row.late_start} < early start {early_side}",
                )
            )

        # --- total float is the gap between them, on the float calendar --
        float_row = slack.get(uid)
        if float_row is None:
            # Already reported as missing above; indexing it here turned that
            # report into a KeyError before it could be returned.
            continue
        start_gap = _signed(activity.float_calendar, early_side, late_row.late_start)
        finish_gap = _signed(activity.float_calendar, row.early_finish, late_row.late_finish)
        measured = min(start_gap, finish_gap)
        reported = float_row.total_float
        if reported != measured:
            violations.append(
                Violation("TOTAL_FLOAT_MISMATCH", uid, f"reported {reported}, measured {measured}")
            )
        # The two components are separately reported and separately consumed,
        # so checking only their minimum left either free to be anything.
        if float_row.start_float != start_gap:
            violations.append(
                Violation(
                    "START_FLOAT_MISMATCH",
                    uid,
                    f"reported {float_row.start_float}, measured {start_gap}",
                )
            )
        if float_row.finish_float != finish_gap:
            violations.append(
                Violation(
                    "FINISH_FLOAT_MISMATCH",
                    uid,
                    f"reported {float_row.finish_float}, measured {finish_gap}",
                )
            )
        # Completed work is never critical whatever its slack (ADR-009,
        # measured on the two files Project itself recalculated), so the
        # threshold rule alone is the wrong question for it -- as the corpus's
        # own status cases said the moment this check was written naively.
        expected_critical = reported <= threshold and state is not ProgressState.COMPLETE
        if float_row.critical != expected_critical:
            violations.append(
                Violation(
                    "CRITICALITY_MISMATCH",
                    uid,
                    f"float {reported}, threshold {threshold}, state {state.value}",
                )
            )

        # --- a constraint the result claims to honour ---------------------
        violations.extend(_constraint_violations(activity, row, early_side))

    # --- free float against the theorem it has to obey -------------------
    # ADR-008 records that free float cannot exceed total float when every
    # outgoing edge is finish-to-start. Measured on the real files while this
    # validator was being written, that holds on one calendar and **not**
    # across several, with no negative float involved: a predecessor whose own
    # calendar is working where its successor's calendar is a gap can slip its
    # own working time without moving the successor at all, so it has free
    # float where the project allows it none. KILN has three such rows,
    # CALCINER five and the day-5 candidate six.
    #
    # So the check asks only of a network where one calendar governs
    # everything, which is where the theorem is sound. That is the conformance
    # corpus, and a regression there fails here.
    single_calendar = len(
        {activity.calendar.intervals for activity in network.activities}
        | {activity.float_calendar.intervals for activity in network.activities}
        | {
            relationship.lag_calendar.intervals
            for relationship in network.relationships
            if relationship.lag_calendar is not None
        }
    ) <= 1
    outgoing: dict[UUID, list] = {uid: [] for uid in activities}
    for relationship in network.relationships:
        if relationship.predecessor_uid in outgoing:
            outgoing[relationship.predecessor_uid].append(relationship)
    for uid, edges in outgoing.items():
        if not single_calendar or uid not in slack or not edges:
            continue
        if states.get(uid) is not ProgressState.NOT_STARTED:
            # A completed row's late dates are pinned to its actuals, so its
            # total float is zero whatever room sits in front of its
            # successors; the theorem compares two quantities that are no
            # longer about the same thing.
            continue
        binding = [
            edge
            for edge in edges
            if relationship_binds(
                progress_policy, states[edge.successor_uid], network.status_time
            )
        ]
        if not binding or not all(
            edge.anchors_predecessor_finish and edge.bounds_successor_start
            for edge in binding
        ):
            continue
        row = slack[uid]
        if row.free_float > row.total_float:
            violations.append(
                Violation(
                    "FREE_FLOAT_EXCEEDS_TOTAL",
                    uid,
                    f"free {row.free_float}, total {row.total_float}, every edge finish-to-start",
                )
            )

    # --- every edge that binds is honoured by the dates it connects ------
    for relationship in network.relationships:
        predecessor = early.get(relationship.predecessor_uid)
        successor = early.get(relationship.successor_uid)
        if predecessor is None or successor is None:
            continue
        if not relationship_binds(
            progress_policy, states[relationship.successor_uid], network.status_time
        ):
            # Released by the policy, or into completed work: the pass did not
            # walk it and neither does this. Every edge it *kept* is checked,
            # including those into work under way, which retained logic really
            # does bound -- skipping them left the one relationship a corrupted
            # in-progress span violates unexamined.
            continue
        anchor = (
            predecessor.early_finish
            if relationship.anchors_predecessor_finish
            else predecessor.early_start
        )
        # The successor side reads its remaining start where it has one, which
        # is the coordinate the edge actually bounds and the one the float
        # measures to.
        successor_start = (
            successor.remaining_start
            if successor.remaining_start is not None
            else successor.early_start
        )
        bound = successor_start if relationship.bounds_successor_start else successor.early_finish
        calendar = (
            relationship.lag_calendar
            if relationship.lag_calendar is not None
            else activities[relationship.successor_uid].calendar
        )
        # Counted, not shifted: the edge asks for ``lag`` of working time
        # between the two coordinates, and a bound earlier than its anchor is
        # a negative amount.
        between = (
            working_between(calendar, anchor, bound)
            if bound >= anchor
            else -working_between(calendar, bound, anchor)
        )
        honoured = between >= relationship.lag
        if honoured and relationship.lag == 0 and bound < anchor:
            # Working time is blind to order inside a gap: two coordinates in
            # the same non-working stretch are zero apart whichever way round
            # they are, so a successor pulled *before* its zero-lag anchor
            # measured as satisfied. Zero lag is a coordinate comparison.
            honoured = False
        if not honoured:
            violations.append(
                Violation(
                    "RELATIONSHIP_NOT_HONOURED",
                    relationship.uid,
                    f"{between} of working time between the ends, lag {relationship.lag}",
                )
            )

    return tuple(violations)


def _constraint_violations(activity, row, early_side: int) -> list[Violation]:
    """A constraint the result claims to honour, checked against its dates.

    The passes apply these; nothing here re-applies them. It asks only whether
    the span that came back satisfies what the network said, because a result
    can be internally well-shaped -- durations right, float consistent -- and
    still sit somewhere its own constraint forbids.
    """

    constraint = activity.constraint_type
    coordinate = activity.constraint_coordinate
    if coordinate is None or constraint in _UNCHECKED_CONSTRAINTS:
        return []
    if activity.has_started:
        # A constraint on work already under way is reported and not applied
        # (ADR-009), so the dates are not claiming to honour it.
        return []
    checks = {
        ConstraintType.SNET: (early_side >= coordinate, "starts before"),
        ConstraintType.SNLT: (early_side <= coordinate, "starts after"),
        ConstraintType.FNET: (row.early_finish >= coordinate, "finishes before"),
        ConstraintType.FNLT: (row.early_finish <= coordinate, "finishes after"),
        ConstraintType.MSO: (early_side == coordinate, "does not start on"),
        ConstraintType.MFO: (row.early_finish == coordinate, "does not finish on"),
    }
    if constraint not in checks:
        return []
    holds, wording = checks[constraint]
    if holds:
        return []
    return [
        Violation(
            "CONSTRAINT_NOT_HONOURED",
            activity.uid,
            f"{constraint.value}: the span {wording} {coordinate}",
        )
    ]


def _signed(calendar, earlier: int, later: int) -> int:
    """Working time from ``earlier`` to ``later``, negative when it runs back."""

    if later >= earlier:
        return working_between(calendar, earlier, later)
    return -working_between(calendar, later, earlier)
