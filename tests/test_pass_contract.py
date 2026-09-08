"""The two passes and the float agree on what they are calculating (slice C2).

The 2026-09-07 comprehensive review reproduced four defects at the seams
between the forward pass, the backward pass and the float. None of them is a
disagreement about a rule: each is one calculation reading an edge, a policy or
a calendar differently from the calculation beside it, which is why a large
passing suite sat above all four. The counterexamples here are the review's
own, with its numbers.
"""

from __future__ import annotations

import unittest
from uuid import NAMESPACE_URL, UUID, uuid5

from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import (
    ForwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    backward_pass,
    float_analysis,
    forward_pass,
    shift_lag,
    unshift_lag,
)
from sto.core.model.enums import ConstraintType, ProgressPolicy, RelationshipType

CONTINUOUS = CompiledIntervals.of(((0, 200),))


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-pass-contract/{name}")


def activity(name, duration, calendar=CONTINUOUS, **fields) -> PlannedActivity:
    return PlannedActivity(uid(name), duration, calendar, **fields)


def link(name, predecessor, successor, type=RelationshipType.FS, lag=0, lag_calendar=None):
    return PlannedRelationship(
        uid(name), uid(predecessor), uid(successor), type, lag, lag_calendar
    )


def network(*activities, relationships=(), project_start=0, horizon=200, status_time=None):
    return Network(
        activities=tuple(activities),
        relationships=tuple(relationships),
        project_start=project_start,
        horizon=horizon,
        status_time=status_time,
    )


class FreeFloatIsWhatThisActivityCanAbsorbTests(unittest.TestCase):
    """F06. The review's counterexample, with its numbers."""

    def _network(self):
        broken = CompiledIntervals.of(((0, 5), (15, 25), (30, 100)))
        return network(
            activity("P", 5, broken),
            activity(
                "S",
                1,
                CONTINUOUS,
                constraint_type=ConstraintType.SNET,
                constraint_coordinate=20,
            ),
            relationships=(link("R1", "P", "S", lag=3, lag_calendar=CONTINUOUS),),
            horizon=100,
        )

    def test_free_float_does_not_exceed_the_delay_that_is_actually_free(self):
        net = self._network()
        forward = forward_pass(net)
        floats = float_analysis(net, forward, backward_pass(net, forward))
        rows = forward.by_uid()
        self.assertEqual(
            (rows[uid("P")].early_start, rows[uid("P")].early_finish), (0, 5)
        )
        self.assertEqual(
            (rows[uid("S")].early_start, rows[uid("S")].early_finish), (20, 21)
        )
        self.assertEqual(floats.by_uid()[uid("P")].total_float, 2)
        # Five was reported before C2: delaying by all five moves the
        # successor to 23, and only two of them were ever free.
        self.assertEqual(floats.by_uid()[uid("P")].free_float, 2)

    def test_and_the_delay_it_reports_really_is_free(self):
        """Re-place the predecessor that much later and read the successor."""

        broken = CompiledIntervals.of(((0, 5), (15, 25), (30, 100)))
        net = self._network()
        forward = forward_pass(net)
        free = float_analysis(net, forward, backward_pass(net, forward)).by_uid()
        slack = free[uid("P")].free_float
        for delay, moves in ((slack, False), (slack + 1, True)):
            with self.subTest(delay=delay):
                delayed = network(
                    activity("P", 5 + delay, broken),
                    activity(
                        "S",
                        1,
                        CONTINUOUS,
                        constraint_type=ConstraintType.SNET,
                        constraint_coordinate=20,
                    ),
                    relationships=(link("R1", "P", "S", lag=3, lag_calendar=CONTINUOUS),),
                    horizon=100,
                )
                start = forward_pass(delayed).by_uid()[uid("S")].early_start
                self.assertEqual(start > 20, moves)


class TheLagInverseIsDefinedByItsInequalityTests(unittest.TestCase):
    """F14. The inverse never lands after the bound it was given."""

    CALENDARS = (
        CompiledIntervals.of(((0, 5), (10, 100))),
        CompiledIntervals.of(((0, 3), (20, 100))),
        CompiledIntervals.of(((0, 4), (9, 12), (30, 100))),
        CompiledIntervals.of(((0, 100),)),
    )
    LAGS = (-7, -5, -3, -2, -1, 0, 1, 2, 3, 5)

    def test_it_never_overshoots_and_nothing_later_would_have_done(self):
        checked = 0
        for calendar in self.CALENDARS:
            for lag in self.LAGS:
                for bound in range(0, 40):
                    back = unshift_lag(calendar, bound, lag)
                    if back is None:
                        continue
                    checked += 1
                    with self.subTest(lag=lag, bound=bound):
                        landing = shift_lag(calendar, back, lag)
                        self.assertIsNotNone(landing)
                        self.assertLessEqual(landing, bound)
                        beyond = shift_lag(calendar, back + 1, lag)
                        self.assertTrue(
                            beyond is None or beyond > bound,
                            f"{back + 1} also lands at or before {bound}",
                        )
        self.assertGreater(checked, 0, "the scan reached no coordinate")


class TheInverseAnswersTheCallerNotTheCalendarTests(unittest.TestCase):
    """Two ways the closed form reached past the question it was asked."""

    def test_a_lead_that_runs_off_the_calendar_is_bounded_by_the_horizon(self):
        # Every coordinate from fifty on lands in the same place, so the lag
        # stops binding there; answering fifty would pull a predecessor on a
        # longer calendar earlier than it needs to be and understate its float.
        calendar = CompiledIntervals.of(((0, 50),))
        self.assertEqual(shift_lag(calendar, 90, -10), shift_lag(calendar, 200, -10))
        self.assertEqual(unshift_lag(calendar, 90, -10), 50)
        self.assertEqual(unshift_lag(calendar, 90, -10, ceiling=200), 200)

    def test_coordinate_zero_is_a_coordinate(self):
        # A calendar whose second interval opens exactly at zero: the answer is
        # zero, and a truthiness test read it as no answer at all.
        calendar = CompiledIntervals.of(((-10, -5), (0, 10)))
        answer = unshift_lag(calendar, -10, -5)
        self.assertEqual(answer, 0)
        self.assertEqual(shift_lag(calendar, answer, -5), -10)


class AReleasedEdgeCannotRefuseTheScheduleTests(unittest.TestCase):
    """F12. The policy decides before the bound is computed."""

    def _network(self, **successor):
        return network(
            activity("P", 80),
            activity("S", 40, **successor),
            relationships=(link("R1", "P", "S", lag=30, lag_calendar=CONTINUOUS),),
            horizon=100,
            status_time=50,
        )

    def test_override_places_the_schedule_the_edge_it_discarded_would_refuse(self):
        net = self._network(actual_start=10, remaining_duration=1)
        rows = forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE).by_uid()
        self.assertEqual(
            (rows[uid("P")].early_start, rows[uid("P")].early_finish), (0, 80)
        )
        self.assertEqual(rows[uid("S")].remaining_start, 50)
        self.assertEqual(rows[uid("S")].early_finish, 51)

    def test_completed_work_reads_no_bound_and_so_refuses_none(self):
        net = self._network(actual_start=10, actual_finish=45)
        rows = forward_pass(net).by_uid()
        self.assertEqual(
            (rows[uid("S")].early_start, rows[uid("S")].early_finish), (10, 45)
        )

    def test_every_calculation_releases_the_completed_edge_together(self):
        """The forward pass alone was not enough.

        Releasing the edge while computing the forward bound left the backward
        pass and the free float still walking it, so the completed case placed
        forward and then refused coming back. Completion belongs to the shared
        applicability decision, where all three calculations read it.
        """

        net = self._network(actual_start=10, actual_finish=45)
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        late = backward.by_uid()[uid("S")]
        self.assertEqual((late.late_start, late.late_finish), (10, 45))
        self.assertIn(uid("R1"), backward.overridden_relationships)
        self.assertIsNotNone(floats.by_uid()[uid("P")].free_float)

    def test_a_lead_the_forward_pass_places_is_not_refused_coming_back(self):
        """The inverse must look above the anchor, not only at it.

        A one-unit lead from a predecessor at 0-1 puts the successor at zero,
        which the forward pass places. Walking the lag back *from* zero runs
        off the beginning of the calendar, and requiring the anchor itself to
        be reachable refused a schedule that had just been placed.
        """

        net = network(
            activity("P", 1),
            activity("S", 1),
            relationships=(link("R1", "P", "S", lag=-1, lag_calendar=CONTINUOUS),),
        )
        forward = forward_pass(net)
        self.assertEqual(forward.by_uid()[uid("S")].early_start, 0)
        backward = backward_pass(net, forward)
        self.assertEqual(backward.by_uid()[uid("P")].late_finish, 1)

    def test_but_retained_logic_does_use_the_edge_and_still_refuses(self):
        """The refusal that is not a defect: this policy reads that bound."""

        net = self._network(actual_start=10, remaining_duration=1)
        with self.assertRaises(ForwardPassError) as raised:
            forward_pass(net, progress_policy=ProgressPolicy.RETAINED_LOGIC)
        # The predecessor finishes at eighty and the lag is thirty, so the
        # remaining work cannot start inside the horizon. Refusing is the
        # honest answer when the policy really does read that bound; the code
        # says which end ran out.
        self.assertIn(
            raised.exception.code,
            {"SCHEDULE_LAG_UNREACHABLE", "SCHEDULE_HORIZON_EXCEEDED"},
        )


class OneApplicabilityDecisionForBothPassesTests(unittest.TestCase):
    """F13. A constraint one pass sets aside is not applied by the other."""

    def test_a_completed_row_defers_its_constraint_in_both_directions_too(self):
        """The deferral has to be recorded before the completed row returns."""

        net = network(
            activity(
                "A",
                10,
                actual_start=1,
                actual_finish=8,
                constraint_type=ConstraintType.MSO,
                constraint_coordinate=20,
            ),
            status_time=50,
        )
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        self.assertEqual(
            [row.type for row in forward.deferred_constraints], [ConstraintType.MSO]
        )
        self.assertEqual(
            [row.type for row in backward.deferred_constraints], [ConstraintType.MSO]
        )

    def test_a_constraint_on_started_work_is_deferred_in_both_directions(self):
        net = network(
            activity(
                "A",
                10,
                actual_start=1,
                remaining_duration=5,
                constraint_type=ConstraintType.MSO,
                constraint_coordinate=20,
            ),
            status_time=50,
        )
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)

        self.assertEqual(
            [row.type for row in forward.deferred_constraints], [ConstraintType.MSO]
        )
        self.assertEqual(
            [row.type for row in backward.deferred_constraints], [ConstraintType.MSO]
        )
        row = forward.by_uid()[uid("A")]
        late = backward.by_uid()[uid("A")]
        self.assertEqual((row.remaining_start, row.early_finish), (50, 55))
        self.assertEqual((late.late_start, late.late_finish), (50, 55))
        # Minus thirty before C2, invented by the two passes disagreeing.
        self.assertEqual(floats.by_uid()[uid("A")].total_float, 0)


if __name__ == "__main__":
    unittest.main()
