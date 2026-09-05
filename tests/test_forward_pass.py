"""The forward pass: what each relationship type means, and what it refuses.

Three kinds of test, deliberately separated.

The hand cases fix the semantics of the four types, of signed lag, of the
calendar snap, of milestones under both snap policies, and of the constraints
that can move an early date. Where a number is asserted it is one the reference
arithmetic determines; where the defining property is what matters -- an SF
successor cannot finish before its predecessor starts -- the property is
asserted rather than a coordinate, because a coordinate would only restate the
fixture.

The refusal cases fix that a network the pass cannot schedule is refused by
code and never guessed at: a cycle, a dangling edge, an activity that will not
fit inside the horizon.

The differential runs random networks through a naive forward pass written here
against the **reference** arithmetic from the conformance corpus -- the
coordinate scan, not the bisect -- and compares it with the engine. It is the
same instrument the calendar slice used, and it has the same bound: it proves
the indexed arithmetic and the placement agree with the reference, not that the
rule for deriving a bound from a predecessor is the rule Microsoft Project
uses. That question belongs to the corpus and to the file oracle.
"""

from __future__ import annotations

import random
import unittest
from uuid import NAMESPACE_URL, UUID, uuid5

from sto.core.calendar.arithmetic import (
    CompiledIntervals,
    consume_duration,
    contains_coordinate,
    shift_working_time,
)
from sto.core.engine import (
    ForwardPass,
    ForwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    forward_pass,
)
from sto.core.model.enums import ConstraintType, RelationshipType

DAY = 86400
CONTINUOUS = CompiledIntervals.of(((0, 400),))


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-forward-pass-test/{name}")


def working_days(days: int = 10) -> CompiledIntervals:
    """An eight-hour day split by an hour at noon, repeated -- BOILER's shape."""

    intervals = []
    for day in range(days):
        base = day * DAY
        intervals.append((base + 8 * 3600, base + 12 * 3600))
        intervals.append((base + 13 * 3600, base + 17 * 3600))
    return CompiledIntervals.of(tuple(intervals))


def activity(
    name: str,
    duration: int,
    calendar: CompiledIntervals = CONTINUOUS,
    constraint: ConstraintType = ConstraintType.ASAP,
    coordinate: int | None = None,
) -> PlannedActivity:
    return PlannedActivity(uid(name), duration, calendar, constraint, coordinate)


def link(
    name: str,
    predecessor: str,
    successor: str,
    type: RelationshipType = RelationshipType.FS,
    lag: int = 0,
    calendar: CompiledIntervals | None = None,
) -> PlannedRelationship:
    return PlannedRelationship(
        uid(name), uid(predecessor), uid(successor), type, lag, calendar
    )


def pair(type: RelationshipType, lag: int = 0) -> ForwardPass:
    """A four-unit A and a three-unit B on a continuous calendar, linked once."""

    network = Network(
        activities=(activity("A", 4), activity("B", 3)),
        relationships=(link("R1", "A", "B", type, lag),),
        project_start=0,
        horizon=400,
    )
    return forward_pass(network)


def span(result: ForwardPass, name: str) -> tuple[int, int]:
    row = result.by_uid()[uid(name)]
    return row.early_start, row.early_finish


class RelationshipTypeTests(unittest.TestCase):
    """Which end each type reads, and which end it bounds."""

    def test_fs_starts_the_successor_at_the_predecessor_finish(self):
        result = pair(RelationshipType.FS)
        self.assertEqual(span(result, "A"), (0, 4))
        self.assertEqual(span(result, "B"), (4, 7))
        self.assertEqual(result.project_finish, 7)

    def test_ss_starts_the_successor_with_the_predecessor(self):
        result = pair(RelationshipType.SS)
        self.assertEqual(span(result, "A"), (0, 4))
        self.assertEqual(span(result, "B"), (0, 3))
        self.assertEqual(result.project_finish, 4)

    def test_ff_finishes_the_successor_with_the_predecessor(self):
        result = pair(RelationshipType.FF)
        self.assertEqual(span(result, "A"), (0, 4))
        self.assertEqual(span(result, "B"), (1, 4))
        self.assertEqual(result.project_finish, 4)

    def test_sf_will_not_finish_the_successor_before_the_predecessor_starts(self):
        result = pair(RelationshipType.SF)
        a_start, _ = span(result, "A")
        _, b_finish = span(result, "B")
        self.assertGreaterEqual(b_finish, a_start)

    def test_the_relationship_that_placed_an_activity_is_reported(self):
        result = pair(RelationshipType.FS)
        self.assertEqual(result.driving_relationships(), (uid("R1"),))
        self.assertEqual(result.by_uid()[uid("B")].source, "relationship")
        self.assertIsNone(result.by_uid()[uid("A")].driving_relationship_uid)


class LagTests(unittest.TestCase):
    """Signed lag, and the one rule that is easy to apply twice."""

    def test_positive_lag_delays_the_successor_by_working_time(self):
        result = pair(RelationshipType.FS, lag=2)
        self.assertEqual(span(result, "B"), (6, 9))

    def test_negative_lag_pulls_the_successor_earlier(self):
        result = pair(RelationshipType.FS, lag=-2)
        self.assertEqual(span(result, "B"), (2, 5))

    def test_zero_lag_does_not_snap_and_placement_does(self):
        """A finish on an interval edge is not moved by the lag, only by placement.

        A four-hour A finishes at noon, which is the morning interval's
        exclusive edge and therefore not working time. Zero lag leaves the
        coordinate alone; the successor's placement then moves it to one.
        Applying the snap in both places would put B an hour later still.
        """

        calendar = working_days()
        network = Network(
            activities=(
                activity("A", 4 * 3600, calendar),
                activity("B", 2 * 3600, calendar),
            ),
            relationships=(link("R1", "A", "B"),),
            project_start=0,
            horizon=10 * DAY,
        )
        result = forward_pass(network)
        self.assertEqual(span(result, "A"), (8 * 3600, 12 * 3600))
        self.assertEqual(span(result, "B"), (13 * 3600, 15 * 3600))

    def test_a_lag_that_leaves_the_calendar_is_refused_by_code(self):
        network = Network(
            activities=(activity("A", 4), activity("B", 3)),
            relationships=(link("R1", "A", "B", RelationshipType.FS, lag=-100),),
            project_start=0,
            horizon=400,
        )
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_LAG_UNREACHABLE")


class ConvergenceTests(unittest.TestCase):
    """More than one predecessor, and more than one kind of bound."""

    def test_the_latest_predecessor_drives(self):
        network = Network(
            activities=(activity("A", 4), activity("B", 6), activity("C", 2)),
            relationships=(link("R1", "A", "C"), link("R2", "B", "C")),
            project_start=0,
            horizon=400,
        )
        result = forward_pass(network)
        self.assertEqual(span(result, "C"), (6, 8))
        self.assertEqual(result.by_uid()[uid("C")].driving_relationship_uid, uid("R2"))

    def test_a_start_bound_and_a_finish_bound_are_both_honoured(self):
        """An SS start bound with an FF finish bound is one placement, not two."""

        network = Network(
            activities=(activity("A", 4), activity("B", 10), activity("C", 2)),
            relationships=(
                link("R1", "A", "C", RelationshipType.SS, lag=3),
                link("R2", "B", "C", RelationshipType.FF),
            ),
            project_start=0,
            horizon=400,
        )
        result = forward_pass(network)
        start, finish = span(result, "C")
        self.assertGreaterEqual(start, 3)
        self.assertGreaterEqual(finish, 10)
        self.assertEqual(finish - start, 2)


class MilestoneTests(unittest.TestCase):
    """A zero-duration activity is a coordinate, and the policy says whether it moves."""

    def _network(self) -> Network:
        calendar = working_days()
        return Network(
            activities=(
                activity("A", 4 * 3600, calendar),
                activity("M", 0, calendar),
            ),
            relationships=(link("R1", "A", "M"),),
            project_start=0,
            horizon=10 * DAY,
        )

    def test_by_default_a_milestone_keeps_the_coordinate_its_logic_gives_it(self):
        result = forward_pass(self._network())
        self.assertEqual(span(result, "M"), (12 * 3600, 12 * 3600))

    def test_under_the_snap_policy_it_moves_to_working_time(self):
        result = forward_pass(self._network(), snap_milestones=True)
        self.assertEqual(span(result, "M"), (13 * 3600, 13 * 3600))

    def test_a_milestone_has_no_duration_to_consume(self):
        result = forward_pass(self._network())
        start, finish = span(result, "M")
        self.assertEqual(start, finish)


class ConstraintTests(unittest.TestCase):
    """The constraints that move an early date, and the ones that cannot."""

    def _with(self, type: ConstraintType, coordinate: int) -> ForwardPass:
        network = Network(
            activities=(activity("A", 4), activity("B", 3, CONTINUOUS, type, coordinate)),
            relationships=(link("R1", "A", "B"),),
            project_start=0,
            horizon=400,
        )
        return forward_pass(network)

    def test_start_no_earlier_than_raises_the_start(self):
        result = self._with(ConstraintType.SNET, 20)
        self.assertEqual(span(result, "B"), (20, 23))
        self.assertEqual(result.by_uid()[uid("B")].source, "constraint")

    def test_a_constraint_earlier_than_the_logic_changes_nothing(self):
        result = self._with(ConstraintType.SNET, 1)
        self.assertEqual(span(result, "B"), (4, 7))
        self.assertEqual(result.by_uid()[uid("B")].source, "relationship")

    def test_finish_no_earlier_than_raises_the_finish(self):
        result = self._with(ConstraintType.FNET, 20)
        self.assertEqual(span(result, "B"), (17, 20))

    def test_must_start_on_overrides_the_logic_and_reports_what_it_broke(self):
        result = self._with(ConstraintType.MSO, 2)
        self.assertEqual(span(result, "B"), (2, 5))
        self.assertEqual(len(result.constraint_violations), 1)
        violation = result.constraint_violations[0]
        self.assertEqual(violation.activity_uid, uid("B"))
        self.assertEqual(violation.coordinate, 2)
        self.assertEqual(violation.logic_required, 4)

    def test_must_finish_on_pins_the_finish(self):
        result = self._with(ConstraintType.MFO, 30)
        self.assertEqual(span(result, "B"), (27, 30))

    def test_a_late_constraint_cannot_pull_an_early_date_and_is_carried(self):
        for type in (ConstraintType.SNLT, ConstraintType.FNLT, ConstraintType.ALAP):
            with self.subTest(type=type):
                result = self._with(type, 20)
                self.assertEqual(span(result, "B"), (4, 7))
                self.assertEqual(
                    [row.type for row in result.deferred_constraints], [type]
                )

    def test_a_dated_constraint_without_its_date_is_refused(self):
        network = Network(
            activities=(activity("A", 4, CONTINUOUS, ConstraintType.SNET, None),),
            project_start=0,
            horizon=400,
        )
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_CONSTRAINT_INCOMPLETE")


class RefusalTests(unittest.TestCase):
    """A network the pass cannot schedule is refused by code, never guessed at."""

    def test_a_cycle_is_refused(self):
        network = Network(
            activities=(activity("A", 1), activity("B", 1)),
            relationships=(link("R1", "A", "B"), link("R2", "B", "A")),
            project_start=0,
            horizon=400,
        )
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_CYCLE")

    def test_an_edge_to_an_activity_that_is_not_here_is_refused(self):
        network = Network(
            activities=(activity("A", 1),),
            relationships=(link("R1", "A", "ghost"),),
            project_start=0,
            horizon=400,
        )
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_UNKNOWN_ACTIVITY")

    def test_an_activity_that_is_its_own_predecessor_is_refused(self):
        network = Network(
            activities=(activity("A", 1),),
            relationships=(link("R1", "A", "A"),),
            project_start=0,
            horizon=400,
        )
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_SELF_RELATIONSHIP")

    def test_two_activities_with_one_identity_are_refused(self):
        network = Network(
            activities=(activity("A", 1), activity("A", 2)), project_start=0, horizon=400
        )
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_DUPLICATE_ACTIVITY")

    def test_a_negative_duration_is_refused(self):
        network = Network(activities=(activity("A", -1),), project_start=0, horizon=400)
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_DURATION_NEGATIVE")

    def test_a_calendar_with_no_working_time_is_refused(self):
        network = Network(
            activities=(activity("A", 1, CompiledIntervals.of(())),),
            project_start=0,
            horizon=400,
        )
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_CALENDAR_EMPTY")

    def test_beyond_the_horizon_is_a_refusal_not_a_guess(self):
        network = Network(activities=(activity("A", 500),), project_start=0, horizon=400)
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_HORIZON_EXCEEDED")

    def test_a_horizon_that_does_not_follow_the_start_is_refused(self):
        network = Network(activities=(activity("A", 1),), project_start=10, horizon=10)
        with self.assertRaises(ForwardPassError) as caught:
            forward_pass(network)
        self.assertEqual(caught.exception.code, "SCHEDULE_HORIZON_INVALID")


class DeterminismTests(unittest.TestCase):
    """The same network answers the same way, and a changed one does not."""

    def test_the_fingerprint_is_stable_across_runs(self):
        self.assertEqual(
            pair(RelationshipType.FS).fingerprint, pair(RelationshipType.FS).fingerprint
        )

    def test_a_changed_lag_changes_the_fingerprint(self):
        self.assertNotEqual(
            pair(RelationshipType.FS).fingerprint,
            pair(RelationshipType.FS, lag=1).fingerprint,
        )

    def test_a_changed_type_changes_the_fingerprint(self):
        self.assertNotEqual(
            pair(RelationshipType.FS).fingerprint, pair(RelationshipType.SS).fingerprint
        )

    def test_activities_come_back_in_topological_order(self):
        result = pair(RelationshipType.FS)
        self.assertEqual(result.order, (uid("A"), uid("B")))


# --- the differential -------------------------------------------------------------


class _Unplaceable(Exception):
    """The reference pass could not place an activity inside the horizon."""


def _reference_span(
    intervals: tuple[tuple[int, int], ...],
    start_bound: int,
    finish_bound: int,
    duration: int,
    horizon: int,
) -> tuple[int, int]:
    """The corpus's coordinate scan: the first start that satisfies both bounds."""

    for coordinate in range(max(0, start_bound), horizon + 1):
        if not contains_coordinate(coordinate, intervals):
            continue
        finish = consume_duration(coordinate, duration, intervals)
        if finish is None or finish > horizon:
            continue
        if finish >= finish_bound:
            return coordinate, finish
    raise _Unplaceable()


def _reference_forward(network: Network) -> dict[UUID, tuple[int, int]]:
    """A naive forward pass over the reference arithmetic, in declaration order.

    Random networks are generated with every edge pointing from a lower index to
    a higher one, so declaration order is a topological order and this does not
    need to compute one.
    """

    placed: dict[UUID, tuple[int, int]] = {}
    incoming = network.predecessors()
    for activity_row in network.activities:
        raw = activity_row.calendar.intervals
        start_bound = finish_bound = network.project_start
        for relationship in incoming[activity_row.uid]:
            predecessor = placed[relationship.predecessor_uid]
            anchor = predecessor[1] if relationship.anchors_predecessor_finish else predecessor[0]
            lag_intervals = (
                relationship.lag_calendar.intervals
                if relationship.lag_calendar is not None
                else raw
            )
            shifted = shift_working_time(anchor, relationship.lag, lag_intervals)
            if shifted is None:
                raise _Unplaceable()
            if relationship.bounds_successor_start:
                start_bound = max(start_bound, shifted)
            else:
                finish_bound = max(finish_bound, shifted)
        placed[activity_row.uid] = _reference_span(
            raw, start_bound, finish_bound, activity_row.duration, network.horizon
        )
    return placed


class ReferenceDifferentialTests(unittest.TestCase):
    """Random networks, the engine against the reference arithmetic.

    What this proves: the indexed placement and the bisect lag agree with the
    coordinate scan and :func:`shift_working_time` over every relationship type
    and both lag signs. What it does not prove: that the bound each type derives
    is the bound Microsoft Project derives -- the same reasoning wrote both
    sides here. The corpus and the file oracle answer that.
    """

    # The calendar slice ran ten thousand scalar trials; one network trial is a
    # coordinate scan per activity, so the count buys breadth here instead.
    TRIALS = 500
    HORIZON = 120

    def setUp(self) -> None:
        self.rng = random.Random(20260903)

    def _random_calendar(self) -> CompiledIntervals:
        intervals = []
        cursor = self.rng.randint(0, 4)
        while cursor < self.HORIZON:
            length = self.rng.randint(1, 9)
            intervals.append((cursor, min(cursor + length, self.HORIZON)))
            cursor += length + self.rng.randint(1, 5)
        return CompiledIntervals.of(tuple(intervals))

    def _random_network(self) -> Network:
        count = self.rng.randint(2, 7)
        calendars = [self._random_calendar() for _ in range(count)]
        activities = tuple(
            PlannedActivity(uid(f"d{index}"), self.rng.randint(1, 6), calendars[index])
            for index in range(count)
        )
        relationships = []
        for successor in range(1, count):
            for predecessor in range(successor):
                if self.rng.random() > 0.45:
                    continue
                relationships.append(
                    PlannedRelationship(
                        uid(f"e{predecessor}-{successor}-{len(relationships)}"),
                        uid(f"d{predecessor}"),
                        uid(f"d{successor}"),
                        self.rng.choice(tuple(RelationshipType)),
                        self.rng.randint(-4, 4),
                        None,
                    )
                )
        return Network(
            activities=activities,
            relationships=tuple(relationships),
            project_start=0,
            horizon=self.HORIZON,
        )

    def test_the_engine_agrees_with_the_reference_on_random_networks(self):
        compared = 0
        for trial in range(self.TRIALS):
            network = self._random_network()
            try:
                expected = _reference_forward(network)
            except _Unplaceable:
                # The reference could not place it; the engine must refuse too.
                with self.assertRaises(ForwardPassError, msg=f"trial {trial}"):
                    forward_pass(network)
                continue
            result = forward_pass(network)
            got = {
                row.uid: (row.early_start, row.early_finish) for row in result.times
            }
            self.assertEqual(got, expected, f"trial {trial}")
            compared += 1
        self.assertGreater(compared, self.TRIALS // 4, "too few networks were placeable")


if __name__ == "__main__":
    unittest.main()
