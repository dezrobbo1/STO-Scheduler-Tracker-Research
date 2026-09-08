"""An independent check on a finished result (slice S6).

Every other test in this package asks the engine to compute something and
compares the answer with an expected one. This module asks a different
question: given a result the engine has already produced, do the relations it
*claims* actually hold?

The distinction is the whole point. A defect in the forward pass shows up in
the forward pass's own answer and in anything that recomputes the answer the
same way -- which is how a suite of five hundred passing tests sat above a
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

from dataclasses import dataclass
from uuid import UUID

from sto.core.calendar.arithmetic import working_between
from sto.core.model.enums import ProgressPolicy

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
    threshold: int = 0,
    progress_policy: ProgressPolicy = ProgressPolicy.RETAINED_LOGIC,
    elapsed: frozenset[UUID] = frozenset(),
) -> tuple[Violation, ...]:
    """Check a finished result against itself, and report what does not hold.

    ``elapsed`` names activities whose span is wall-clock rather than working
    time. They are placed on a continuous calendar, so the span check below
    holds for them too, but the caller knows which they are and saying so keeps
    the rule visible rather than implied.

    An empty tuple is the answer for a sound result. Violations carry a code so
    a caller can act on the class rather than parse prose.
    """

    violations: list[Violation] = []
    early = forward.by_uid()
    late = backward.by_uid()
    slack = floats.by_uid()
    activities = {activity.uid: activity for activity in network.activities}
    states = {uid: state_of(activity) for uid, activity in activities.items()}

    # --- every row is answered exactly once, by all three ---------------
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

        if state is ProgressState.COMPLETE:
            # Reported dates are facts, not placements: they consume whatever
            # they consume, and nothing recomputes them.
            continue

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

        # --- the late span is not earlier than the early one -------------
        if late_row.late_start < row.early_start:
            violations.append(
                Violation(
                    "LATE_BEFORE_EARLY",
                    uid,
                    f"late start {late_row.late_start} < early start {row.early_start}",
                )
            )

        # --- total float is the gap between them, on the float calendar --
        measured = min(
            _signed(activity.float_calendar, row.early_start, late_row.late_start),
            _signed(activity.float_calendar, row.early_finish, late_row.late_finish),
        )
        reported = slack[uid].total_float
        if reported != measured:
            violations.append(
                Violation("TOTAL_FLOAT_MISMATCH", uid, f"reported {reported}, measured {measured}")
            )
        if slack[uid].critical != (reported <= threshold):
            violations.append(
                Violation("CRITICALITY_MISMATCH", uid, f"float {reported}, threshold {threshold}")
            )

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
            continue
        if states[relationship.successor_uid] is not ProgressState.NOT_STARTED:
            # The successor's remaining work is placed by the policy, not by
            # this edge; the pass reports which edges it released and this is
            # not the place to second-guess the ones it kept.
            continue
        anchor = (
            predecessor.early_finish
            if relationship.anchors_predecessor_finish
            else predecessor.early_start
        )
        bound = (
            successor.early_start
            if relationship.bounds_successor_start
            else successor.early_finish
        )
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
        if between < relationship.lag:
            violations.append(
                Violation(
                    "RELATIONSHIP_NOT_HONOURED",
                    relationship.uid,
                    f"{between} of working time between the ends, lag {relationship.lag}",
                )
            )

    return tuple(violations)


def _signed(calendar, earlier: int, later: int) -> int:
    """Working time from ``earlier`` to ``later``, negative when it runs back."""

    if later >= earlier:
        return working_between(calendar, earlier, later)
    return -working_between(calendar, later, earlier)
