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

from sto.core.calendar.arithmetic import add_working, next_working, sub_working, working_between
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
VALIDATOR_PROFILE = "sto-validator-v2"


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
    progress_policy: ProgressPolicy | None = None,
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
    # The policy is recorded on both passes and hashed into their fingerprints,
    # so the result already says which one produced it. Defaulting to retained
    # logic instead read a sound override result as a broken retained-logic one
    # whenever the caller used the ordinary four-argument form.
    if progress_policy is None:
        progress_policy = forward.progress_policy
    elif progress_policy is not forward.progress_policy:
        return (
            Violation(
                "SCHEDULE_POLICY_MISMATCH",
                None,
                f"asked for {progress_policy.value}, computed under "
                f"{forward.progress_policy.value}",
            ),
        )
    violations: list[Violation] = []

    # --- the passes describe *this* network ------------------------------
    # Both passes hash the network they ran over, and `float_analysis` already
    # refuses a mismatched pair. Nothing checked the pair against the network
    # in hand, so a result computed over the same activities under a different
    # horizon validated cleanly against the current one -- which is how a stale
    # stored calculation gets blessed as belonging to a schedule it does not.
    fingerprint = network.fingerprint()
    for name, seen in (("FORWARD", forward.network_fingerprint), ("BACKWARD", backward.network_fingerprint)):
        if seen != fingerprint:
            violations.append(
                Violation(
                    f"{name}_NETWORK_MISMATCH",
                    None,
                    f"the pass ran over {seen}, this network is {fingerprint}",
                )
            )
    if violations:
        # Every check below reads rows keyed by this network's activities.
        # Measuring them against a pass that ran over another one produces
        # noise, not findings.
        return tuple(violations)

    # --- the coordinates the result carries about the whole project ------
    # Three numbers sit outside every row and are read as if they described
    # them: the window the forward pass says it worked in, and the finish the
    # float measured open-ended tails against. Nothing compared them with the
    # network or with each other, so a stored result could name a project start
    # its own rows contradict.
    if forward.project_start != network.project_start:
        violations.append(
            Violation(
                "PROJECT_START_MISMATCH",
                None,
                f"the pass says {forward.project_start}, the network {network.project_start}",
            )
        )
    if forward.times:
        latest = max(row.early_finish for row in forward.times)
        if forward.project_finish != latest:
            violations.append(
                Violation(
                    "PROJECT_FINISH_MISMATCH",
                    None,
                    f"the pass says {forward.project_finish}, its own rows end at {latest}",
                )
            )
    if floats.project_late_finish != backward.project_late_finish:
        violations.append(
            Violation(
                "PROJECT_LATE_FINISH_MISMATCH",
                None,
                f"the float says {floats.project_late_finish}, "
                f"the backward pass {backward.project_late_finish}",
            )
        )

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

    incident: dict[UUID, dict[UUID, object]] = {uid: {} for uid in activities}
    outgoing: dict[UUID, list] = {uid: [] for uid in activities}
    for relationship in network.relationships:
        if relationship.successor_uid in incident:
            incident[relationship.successor_uid][relationship.uid] = relationship
        if relationship.predecessor_uid in outgoing:
            outgoing[relationship.predecessor_uid].append(relationship)

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
                # Both supported policies raise remaining work to the status
                # date: override replaces the logic bound with it, retained
                # logic takes the later of the two. Applying the floor only for
                # override left a retained-logic row free to resume before the
                # date it is reported as at.
                floor = activity.actual_start
                if network.status_time is not None:
                    floor = (
                        network.status_time
                        if floor is None
                        else max(floor, network.status_time)
                    )
                if floor is not None and row.remaining_start < floor:
                    violations.append(
                        Violation(
                            "REMAINING_START_BEFORE_ITS_FLOOR",
                            uid,
                            f"remaining start {row.remaining_start} < {floor}",
                        )
                    )

        # --- the state and the actuals the row reports -------------------
        # Both passes and the projection consume ``state``; nothing compared it
        # with the activity it describes, so a row could claim to be finished
        # while its source said otherwise and every date check still passed.
        if row.state is not state:
            violations.append(
                Violation(
                    "PROGRESS_STATE_MISMATCH",
                    uid,
                    f"reported {row.state.value}, source says {state.value}",
                )
            )
        # Reported dates are facts, not answers: the exemption above lets a
        # completed span consume whatever it consumes, and without this it also
        # let the span be moved anywhere at all.
        if state is ProgressState.COMPLETE:
            # Both copies of history, not just the forward one. Where the
            # actuals sit in a non-working gap the float measures zero either
            # way, so the late span could be moved anywhere in that gap and
            # every arithmetic check still agreed.
            if activity.actual_start is not None and late_row.late_start != activity.actual_start:
                violations.append(
                    Violation(
                        "COMPLETED_LATE_START_NOT_ITS_ACTUAL",
                        uid,
                        f"late start {late_row.late_start}, actual start {activity.actual_start}",
                    )
                )
            if activity.actual_finish is not None and late_row.late_finish != activity.actual_finish:
                violations.append(
                    Violation(
                        "COMPLETED_LATE_FINISH_NOT_ITS_ACTUAL",
                        uid,
                        f"late finish {late_row.late_finish}, actual finish {activity.actual_finish}",
                    )
                )
            if activity.actual_start is not None and row.early_start != activity.actual_start:
                violations.append(
                    Violation(
                        "COMPLETED_START_NOT_ITS_ACTUAL",
                        uid,
                        f"early start {row.early_start}, actual start {activity.actual_start}",
                    )
                )
            if activity.actual_finish is not None and row.early_finish != activity.actual_finish:
                violations.append(
                    Violation(
                        "COMPLETED_FINISH_NOT_ITS_ACTUAL",
                        uid,
                        f"early finish {row.early_finish}, actual finish {activity.actual_finish}",
                    )
                )
        elif state is ProgressState.IN_PROGRESS:
            # The coordinate exists for exactly this state. Where the actual
            # start happens to equal it, dropping it changed no duration and no
            # float, and the structural checks that read it were all guarded on
            # its presence -- so its absence was invisible.
            if row.remaining_start is None:
                violations.append(
                    Violation(
                        "REMAINING_START_MISSING",
                        uid,
                        "work under way reports no remaining start",
                    )
                )
            if activity.actual_start is not None and row.early_start != activity.actual_start:
                violations.append(
                    Violation(
                        "STARTED_WORK_MOVED_OFF_ITS_ACTUAL",
                        uid,
                        f"early start {row.early_start}, actual start {activity.actual_start}",
                    )
                )
        # --- and a root begins no earlier than the project does ----------
        # Only of a root: an activity with nothing bounding it and no dated
        # constraint has the project start as its floor, and nothing else can
        # have placed it earlier. It is *not* a rule for the whole network. The
        # forward pass floors the start side at the project start and the
        # finish side at the calendar floor, deliberately (ADR-010), so an
        # activity bounded on its finish reaches back before the project start
        # on every real file here -- 56 rows on the un-progressed BOILER
        # snapshot alone. Asking it of them would reject sound results.
        elif (
            not incident[uid]
            and activity.constraint_coordinate is None
            and row.early_start < network.project_start
        ):
            violations.append(
                Violation(
                    "EARLY_START_BEFORE_PROJECT_START",
                    uid,
                    f"early start {row.early_start} < project start {network.project_start}",
                )
            )

        # A late span earlier than its early one is not a structural fault. It
        # is what negative float *is*: an overcommitted schedule, an FNLT that
        # cannot be met, reports exactly that shape and is sound. The float
        # measurement below already covers the case, because the gap it
        # measures is signed and is compared with the number the result
        # reports -- so an ordering rule here only rejected sound results.
        #
        # The comparison is against the *remaining* start where there is one:
        # for work under way the early start is the immovable actual one while
        # the late dates describe the part that can still move.
        early_side = row.remaining_start if row.remaining_start is not None else row.early_start

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
        # ``complete`` is the row's own statement of *why* it is not critical
        # -- it is done, rather than it has slack -- and both are consumed.
        if float_row.complete != (state is ProgressState.COMPLETE):
            violations.append(
                Violation(
                    "COMPLETE_FLAG_MISMATCH",
                    uid,
                    f"reported {float_row.complete}, source says {state.value}",
                )
            )
        expected_critical = reported <= threshold and state is not ProgressState.COMPLETE
        if float_row.critical != expected_critical:
            violations.append(
                Violation(
                    "CRITICALITY_MISMATCH",
                    uid,
                    f"float {reported}, threshold {threshold}, state {state.value}",
                )
            )

        # --- the edge the row names as its driver ------------------------
        # ``driving_relationships()`` and the stored result both publish this,
        # and nothing looked at it: a row could name an edge that does not
        # exist, or one it is not on, and every date still measured correctly.
        violations.extend(
            _driver_violations(uid, row.driving_relationship_uid, incident, "FORWARD")
        )
        # The backward pass is driven by the edge *out of* the activity: what
        # bounds its late dates is a successor, not a predecessor.
        violations.extend(
            _driver_violations(
                uid,
                late_row.driving_relationship_uid,
                {uid: {edge.uid: edge for edge in outgoing.get(uid, ())}},
                "BACKWARD",
            )
        )

        # --- a constraint the result claims to honour ---------------------
        violations.extend(_constraint_violations(activity, row, late_row, early_side))

    # --- free float, recomputed rather than bounded -----------------------
    # The first version of this check asked only that free float not exceed
    # total float. That is a theorem, not a measurement: it left the reported
    # value free to be anything below the bound, and it is false where total
    # float is negative -- a chain that is already late has no slack and free
    # float of zero, which the inequality called a violation.
    #
    # So the reported number is checked by applying it. An activity with that
    # much free float can slip by exactly that much without moving a successor,
    # and no further. Both halves are asked, because only the pair pins the
    # value: the first alone accepts anything too small, the second anything
    # too large. Nothing here inverts a lag; the edges are re-measured with the
    # same counting the edge check uses.
    released = frozenset(backward.overridden_relationships)
    for uid, activity in activities.items():
        row = early.get(uid)
        float_row = slack.get(uid)
        if row is None or float_row is None:
            continue
        edges = [edge for edge in outgoing.get(uid, ()) if edge.uid not in released]
        reported = float_row.free_float
        if not edges:
            # An open-ended tail is measured against the project late finish,
            # which is what makes its free float equal its total float rather
            # than unbounded.
            expected = _signed(
                activity.float_calendar, row.early_finish, backward.project_late_finish
            )
            if reported != expected:
                violations.append(
                    Violation(
                        "FREE_FLOAT_MISMATCH",
                        uid,
                        f"reported {reported}, measured {expected} to the project finish",
                    )
                )
            continue
        # The two halves are asked separately, and each on its own terms. A
        # reported float that is negative slips *backwards*, which can run off
        # the start of the calendar and leave the first question unanswerable;
        # the second question does not depend on the first, and it is the one
        # that catches an understated float.
        holds = _edges_hold_after(reported, row, activity, edges, early, activities,
                                  snap_milestones=forward.snap_milestones)
        further = _edges_hold_after(reported + 1, row, activity, edges, early, activities,
                                  snap_milestones=forward.snap_milestones)
        if further is True:
            # Asked first, because it answers on its own terms: one more unit
            # of slip moves nothing, so the reported number is understated
            # whether or not the reported slip itself could be applied.
            violations.append(
                Violation(
                    "FREE_FLOAT_TOO_SMALL",
                    uid,
                    f"slipping {reported + 1} still moves nothing",
                )
            )
        elif holds is False:
            violations.append(
                Violation(
                    "FREE_FLOAT_TOO_LARGE",
                    uid,
                    f"slipping {reported} moves a successor",
                )
            )
        elif holds is None:
            # Neither probe lands on the calendar, so the number cannot be
            # applied at all. That is not agreement: a free float of minus a
            # hundred is unanswerable in exactly this way, and treating silence
            # as a pass let it through.
            violations.append(
                Violation(
                    "FREE_FLOAT_UNANSWERABLE",
                    uid,
                    f"slipping {reported} leaves the calendar",
                )
            )

    # --- every edge that binds is honoured by the dates it connects ------
    # An MSO or MFO date wins against precedence -- that is what makes it hard
    # in the canonical model -- and the forward pass reports what it displaced
    # rather than pretending the edge held. Asking those successors to honour
    # the edge anyway rejected the pass's own documented behaviour.
    displaced = {violation.activity_uid for violation in forward.constraint_violations}
    for relationship in network.relationships:
        predecessor = early.get(relationship.predecessor_uid)
        successor = early.get(relationship.successor_uid)
        if predecessor is None or successor is None:
            continue
        if relationship.successor_uid in displaced:
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


def _driver_violations(uid, driver, incident, side: str) -> list[Violation]:
    """The edge a row names as what placed it, checked against the network.

    A named driver is a claim like any other: that the edge exists, that this
    activity is its successor, and that it is one of the edges the pass walked.
    Nothing checked it, so a row could name an edge from another schedule and
    every date on it still measure correctly.
    """

    if driver is None:
        return []
    edges = incident.get(uid, {})
    if driver not in edges:
        return [
            Violation(
                f"{side}_DRIVER_NOT_INCIDENT",
                uid,
                f"names {driver}, which is not an edge into this activity",
            )
        ]
    return []


def _slipped(calendar, coordinate: int, amount: int) -> int | None:
    """``coordinate`` moved ``amount`` of working time, forwards or back."""

    if amount == 0:
        return coordinate
    if amount > 0:
        return add_working(calendar, coordinate, amount)
    return sub_working(calendar, coordinate, -amount)


def _edges_hold_after(
    slip: int,
    row,
    activity,
    edges,
    early,
    activities,
    *,
    snap_milestones: bool = False,
) -> bool | None:
    """Would every outgoing edge still hold if this activity slipped that far?

    This is how free float is checked without inverting a lag: the reported
    slack is applied to the activity's own span and the edges are re-measured
    with the same counting the edge check uses. ``None`` means the question
    cannot be asked -- the slip leaves the calendar -- which the caller reports
    rather than treats as a pass.
    """

    start = (row.early_start if activity.has_started else
             _slipped(activity.float_calendar, row.early_start, slip))
    finish = _slipped(activity.float_calendar, row.early_finish, slip)
    if start is None or finish is None:
        return None
    exactly_pinned = (
        row.state is ProgressState.NOT_STARTED
        and activity.constraint_type in (ConstraintType.MSO, ConstraintType.MFO)
    )
    snapped_zero = (
        snap_milestones and activity.remaining == 0
        and row.state is not ProgressState.COMPLETE and not exactly_pinned
    )
    # Apply the forward placement domain to the independently slipped anchor.
    # An exclusive interval end is a finish, but a start bound there advances
    # to the next interval. Actual starts and exact pins are not snapped.
    if (row.state is ProgressState.NOT_STARTED and not exactly_pinned
            and (activity.remaining > 0 or snapped_zero)):
        start = next_working(activity.calendar, start)
    if snapped_zero:
        finish = next_working(activity.calendar, finish)
    for edge in edges:
        successor = early.get(edge.successor_uid)
        if successor is None:
            return None
        # A historical start cannot consume a nonzero start-side slip.
        if activity.has_started and not edge.anchors_predecessor_finish and slip != 0:
            return False
        anchor = finish if edge.anchors_predecessor_finish else start
        if anchor is None:
            return False  # No placement exists at or after this bound.
        available = (
            (successor.remaining_start if successor.remaining_start is not None
             else successor.early_start)
            if edge.bounds_successor_start
            else successor.early_finish
        )
        calendar = (
            edge.lag_calendar
            if edge.lag_calendar is not None
            else activities[edge.successor_uid].calendar
        )
        between = (
            working_between(calendar, anchor, available)
            if available >= anchor
            else -working_between(calendar, available, anchor)
        )
        if between < edge.lag:
            return False
        if edge.lag == 0 and available < anchor:
            return False
    return True

def _constraint_violations(activity, row, late_row, early_side: int) -> list[Violation]:
    """A constraint the result claims to honour, checked against its dates.

    The passes apply these; nothing here re-applies them. It asks only whether
    the span that came back satisfies what the network said, because a result
    can be internally well-shaped -- durations right, float consistent -- and
    still sit somewhere its own constraint forbids.

    **Which span to ask of.** Each constraint is answered by the pass that
    applies it. The forward pass applies the no-earlier-than pair and the
    must-be-on pair; the backward pass applies the no-later-than pair, and the
    forward pass deliberately leaves an early finish beyond an FNLT it cannot
    meet, carrying the shortfall as negative float. Asking the early span
    about a no-later-than constraint therefore rejected sound results.
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
        ConstraintType.FNET: (row.early_finish >= coordinate, "finishes before"),
        ConstraintType.SNLT: (
            late_row.late_start <= coordinate,
            "is bounded to start after",
        ),
        ConstraintType.FNLT: (
            late_row.late_finish <= coordinate,
            "is bounded to finish after",
        ),
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
