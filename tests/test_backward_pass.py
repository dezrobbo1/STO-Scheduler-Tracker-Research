"""The backward pass, its float, and the properties that tie it to the forward one.

Two kinds of test. The first is the ordinary kind: hand networks with an answer
worked out on paper, over all four relationship types, signed lag, the
constraints the pass applies and the one it refuses to.

The second is the kind that matters more, because the backward pass is a mirror
and a mirror is exactly the sort of code that is wrong in one direction only.
Those tests state a relation between the two passes and check it over generated
networks: a chain with no slack has late dates equal to its early ones; every
activity's late span consumes the same working time as its early span; free
float never exceeds total float; and moving the project's late finish moves
every float by the same amount. None of them would pass if a bound were read
off the wrong end.

Coordinates here are plain integers on a continuous calendar unless the case is
about a calendar, because the calendar arithmetic is
``tests/test_calendar_arithmetic.py``'s subject and not this module's.
"""

from __future__ import annotations

import unittest
from uuid import NAMESPACE_URL, UUID, uuid5

from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import (
    BackwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    backward_pass,
    float_analysis,
    forward_pass,
)
from sto.core.model.enums import ConstraintType, RelationshipType

HORIZON = 400
CONTINUOUS = CompiledIntervals.of([(0, HORIZON)])
#: Four on, one off, four on, a night, then the same again -- SEM-CAL-021's shape.
BROKEN = CompiledIntervals.of([(0, 4), (5, 9), (24, 28), (29, 33)])


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-test/backward/{name}")


def activity(
    name: str,
    duration: int,
    *,
    calendar: CompiledIntervals = CONTINUOUS,
    constraint: ConstraintType = ConstraintType.ASAP,
    coordinate: int | None = None,
) -> PlannedActivity:
    return PlannedActivity(
        uid=uid(name),
        duration=duration,
        calendar=calendar,
        constraint_type=constraint,
        constraint_coordinate=coordinate,
    )


def edge(
    name: str,
    predecessor: str,
    successor: str,
    kind: RelationshipType = RelationshipType.FS,
    lag: int = 0,
    lag_calendar: CompiledIntervals | None = None,
) -> PlannedRelationship:
    return PlannedRelationship(
        uid=uid(name),
        predecessor_uid=uid(predecessor),
        successor_uid=uid(successor),
        type=kind,
        lag=lag,
        lag_calendar=lag_calendar,
    )


def network(activities, relationships=(), project_start=0, horizon=HORIZON) -> Network:
    return Network(
        activities=tuple(activities),
        relationships=tuple(relationships),
        project_start=project_start,
        horizon=horizon,
    )


def passes(net: Network, **kwargs):
    """Both passes and the float, which is how every caller uses them."""

    forward = forward_pass(net, snap_milestones=kwargs.pop("snap_milestones", False))
    backward = backward_pass(net, forward, **kwargs)
    return forward, backward, float_analysis(net, forward, backward)


def late(backward, name: str) -> tuple[int, int]:
    row = backward.by_uid()[uid(name)]
    return row.late_start, row.late_finish


class RelationshipTypeTests(unittest.TestCase):
    """Each type bounds the end going back that it bounded coming forward.

    One shape, four readings. A two-day predecessor and a three-day successor
    with the project's late finish taken from the forward pass, so the answer
    says which end of the successor was read and which end of the predecessor
    it landed on.
    """

    def _chain(self, kind: RelationshipType, lag: int = 0):
        net = network(
            [activity("A", 2), activity("B", 3)],
            [edge("R", "A", "B", kind, lag)],
        )
        return passes(net)

    def test_fs_bounds_the_predecessor_finish_at_the_successor_late_start(self):
        forward, backward, _ = self._chain(RelationshipType.FS)
        self.assertEqual(forward.project_finish, 5)
        self.assertEqual(late(backward, "B"), (2, 5))
        self.assertEqual(late(backward, "A"), (0, 2))

    def test_ss_bounds_the_predecessor_start_at_the_successor_late_start(self):
        forward, backward, _ = self._chain(RelationshipType.SS)
        # B may start when A starts, so both run to the project finish at 3.
        self.assertEqual(forward.project_finish, 3)
        self.assertEqual(late(backward, "B"), (0, 3))
        self.assertEqual(late(backward, "A"), (0, 2))

    def test_ff_bounds_the_predecessor_finish_at_the_successor_late_finish(self):
        forward, backward, _ = self._chain(RelationshipType.FF)
        self.assertEqual(forward.project_finish, 3)
        self.assertEqual(late(backward, "B"), (0, 3))
        # A's finish is bounded by B's late finish, not by B's late start.
        self.assertEqual(late(backward, "A"), (1, 3))

    def test_sf_bounds_the_predecessor_start_at_the_successor_late_finish(self):
        forward, backward, _ = self._chain(RelationshipType.SF)
        self.assertEqual(forward.project_finish, 3)
        self.assertEqual(late(backward, "B"), (0, 3))
        # SF bounds A's *start* at B's late finish, so A may start as late as 3
        # -- but nothing may finish after the project late finish, and A needs
        # two units, so the finish bound is what actually binds.
        self.assertEqual(late(backward, "A"), (1, 3))

    def test_positive_lag_pulls_the_predecessor_back_by_the_same_amount(self):
        _, plain, _ = self._chain(RelationshipType.FS, 0)
        _, lagged, _ = self._chain(RelationshipType.FS, 4)
        self.assertEqual(late(plain, "A"), (0, 2))
        # The successor still ends at the project finish, which the lag moved.
        self.assertEqual(late(lagged, "A"), (0, 2))
        self.assertEqual(late(lagged, "B"), (6, 9))

    def test_negative_lag_pushes_the_predecessor_forward(self):
        _, backward, _ = self._chain(RelationshipType.FS, -1)
        # B starts one unit before A finishes, so A's late finish is B's late
        # start plus the unit the negative lag gave back.
        self.assertEqual(late(backward, "B"), (1, 4))
        self.assertEqual(late(backward, "A"), (0, 2))

    def test_zero_lag_does_not_snap_a_bound_out_of_a_gap(self):
        """The mirror of the forward pass's rule, and the same reason for it.

        Snapping in the lag as well as in placement moves a predecessor a whole
        interval too far -- in this direction, too early rather than too late.
        """

        net = network(
            [activity("A", 2, calendar=BROKEN), activity("B", 2, calendar=BROKEN)],
            [edge("R", "A", "B")],
        )
        forward, backward, floats = passes(net)
        early = forward.by_uid()
        self.assertEqual(early[uid("A")].early_finish, 2)
        # Nothing has slack in a two-activity chain that defines its own finish.
        self.assertEqual(floats.by_uid()[uid("A")].total_float, 0)
        self.assertEqual(late(backward, "A"), (0, 2))


class MergeAndSpreadTests(unittest.TestCase):
    def test_the_tightest_successor_wins(self):
        """Two successors, and the one that needs the predecessor sooner binds."""

        net = network(
            [activity("A", 1), activity("B", 5), activity("C", 1)],
            [edge("R1", "A", "B"), edge("R2", "A", "C")],
        )
        forward, backward, floats = passes(net)
        self.assertEqual(forward.project_finish, 6)
        self.assertEqual(late(backward, "B"), (1, 6))
        self.assertEqual(late(backward, "C"), (5, 6))
        # A is held by B, the successor with no slack of its own.
        self.assertEqual(late(backward, "A"), (0, 1))
        self.assertEqual(floats.by_uid()[uid("A")].total_float, 0)
        self.assertEqual(floats.by_uid()[uid("C")].total_float, 4)

    def test_an_activity_with_no_successors_hangs_off_the_project_finish(self):
        net = network([activity("A", 2), activity("B", 5)])
        forward, backward, floats = passes(net)
        self.assertEqual(forward.project_finish, 5)
        self.assertEqual(late(backward, "A"), (3, 5))
        self.assertEqual(floats.by_uid()[uid("A")].total_float, 3)
        self.assertEqual(floats.by_uid()[uid("B")].total_float, 0)

    def test_the_driving_relationship_is_the_one_that_held_the_activity_back(self):
        net = network(
            [activity("A", 1), activity("B", 5), activity("C", 1)],
            [edge("R1", "A", "B"), edge("R2", "A", "C")],
        )
        _, backward, _ = passes(net)
        row = backward.by_uid()[uid("A")]
        self.assertEqual(row.driving_relationship_uid, uid("R1"))
        self.assertIn(uid("R1"), backward.driving_relationships())


class ConstraintTests(unittest.TestCase):
    def test_finish_no_later_than_lowers_the_late_finish(self):
        """The chain starts at 10 so the late dates have somewhere to go.

        A late constraint that cannot be met pushes late dates *before* the
        project start, which is what an over-committed schedule looks like and
        is reported as negative float rather than refused.
        """

        net = network(
            [activity("A", 2), activity("B", 3)],
            [edge("R", "A", "B")],
            project_start=10,
        )
        _, _, plain_floats = passes(net)
        self.assertEqual(plain_floats.by_uid()[uid("B")].total_float, 0)

        constrained = network(
            [
                activity("A", 2),
                activity("B", 3, constraint=ConstraintType.FNLT, coordinate=14),
            ],
            [edge("R", "A", "B")],
            project_start=10,
        )
        forward, backward, floats = passes(constrained)
        self.assertEqual(forward.project_finish, 15)
        self.assertEqual(late(backward, "B"), (11, 14))
        # The forward pass puts B at 12..15 and the constraint says 14, so the
        # schedule is one unit short: negative float, not a moved early date.
        self.assertEqual(floats.by_uid()[uid("B")].total_float, -1)
        self.assertTrue(floats.by_uid()[uid("B")].negative)
        # A is dragged with it, and its late start falls before the project's.
        self.assertEqual(late(backward, "A"), (9, 11))
        self.assertEqual(floats.negative_float_activities(), (uid("A"), uid("B")))

    def test_start_no_later_than_lowers_the_late_start(self):
        """A parallel activity carries the project finish out past the bound.

        Without one the project finish binds first and the constraint never
        shows -- which is itself the reason the case needs two activities.
        """

        plain = network([activity("A", 2), activity("B", 9)])
        _, _, unconstrained = passes(plain)
        self.assertEqual(unconstrained.by_uid()[uid("A")].total_float, 7)

        net = network(
            [
                activity("A", 2, constraint=ConstraintType.SNLT, coordinate=5),
                activity("B", 9),
            ]
        )
        _, backward, floats = passes(net)
        self.assertEqual(late(backward, "A"), (5, 7))
        self.assertEqual(floats.by_uid()[uid("A")].total_float, 5)

    def test_a_late_constraint_that_is_not_binding_changes_nothing(self):
        net = network([activity("A", 2), activity("B", 5)])
        _, plain, _ = passes(net)
        relaxed = network(
            [
                activity("A", 2, constraint=ConstraintType.FNLT, coordinate=99),
                activity("B", 5),
            ]
        )
        _, backward, _ = passes(relaxed)
        self.assertEqual(late(backward, "A"), late(plain, "A"))

    def test_must_start_on_pins_the_late_dates_where_it_pinned_the_early_ones(self):
        net = network(
            [
                activity("A", 2, constraint=ConstraintType.MSO, coordinate=6),
                activity("B", 5),
            ]
        )
        forward, backward, floats = passes(net)
        early = forward.by_uid()[uid("A")]
        self.assertEqual((early.early_start, early.early_finish), (6, 8))
        self.assertEqual(late(backward, "A"), (6, 8))
        # A hard constraint leaves no float in either direction.
        self.assertEqual(floats.by_uid()[uid("A")].total_float, 0)

    def test_must_finish_on_pins_the_late_dates_too(self):
        net = network(
            [
                activity("A", 2, constraint=ConstraintType.MFO, coordinate=6),
                activity("B", 9),
            ]
        )
        _, backward, floats = passes(net)
        self.assertEqual(late(backward, "A"), (4, 6))
        self.assertEqual(floats.by_uid()[uid("A")].total_float, 0)

    def test_as_late_as_possible_is_carried_through_rather_than_guessed_at(self):
        """ALAP moves where an activity sits, so neither pass may answer it."""

        net = network(
            [activity("A", 2, constraint=ConstraintType.ALAP), activity("B", 5)]
        )
        forward, backward, _ = passes(net)
        self.assertEqual(
            [row.type for row in forward.deferred_constraints], [ConstraintType.ALAP]
        )
        self.assertEqual(
            [row.type for row in backward.deferred_constraints], [ConstraintType.ALAP]
        )
        self.assertEqual(
            [row.activity_uid for row in backward.deferred_constraints], [uid("A")]
        )


class MilestoneTests(unittest.TestCase):
    def test_a_milestone_keeps_its_coordinate_when_the_policy_says_not_to_snap(self):
        net = network(
            [activity("A", 4, calendar=BROKEN), activity("M", 0, calendar=BROKEN)],
            [edge("R", "A", "M")],
        )
        forward, backward, _ = passes(net)
        # A ends on the exclusive edge of the first interval; M stays there.
        self.assertEqual(forward.by_uid()[uid("M")].early_start, 4)
        self.assertEqual(late(backward, "M"), (4, 4))

    def test_snapping_moves_a_milestone_back_to_a_working_coordinate(self):
        net = network(
            [activity("A", 4, calendar=BROKEN), activity("M", 0, calendar=BROKEN)],
            [edge("R", "A", "M")],
        )
        forward = forward_pass(net, snap_milestones=True)
        backward = backward_pass(net, forward, snap_milestones=True)
        self.assertEqual(forward.by_uid()[uid("M")].early_start, 5)
        self.assertEqual(late(backward, "M"), (5, 5))


class ProjectLateFinishTests(unittest.TestCase):
    def test_a_required_finish_moves_every_float_by_the_same_amount(self):
        net = network(
            [activity("A", 2), activity("B", 3), activity("C", 1)],
            [edge("R", "A", "B")],
        )
        forward = forward_pass(net)
        base = float_analysis(net, forward, backward_pass(net, forward))
        later = float_analysis(
            net, forward, backward_pass(net, forward, project_late_finish=8)
        )
        for row in base.rows:
            self.assertEqual(
                later.by_uid()[row.uid].total_float - row.total_float,
                3,
                f"{row.uid} did not move with the project late finish",
            )

    def test_an_earlier_required_finish_makes_the_longest_path_negative(self):
        net = network([activity("A", 5)], project_start=10)
        forward = forward_pass(net)
        floats = float_analysis(
            net, forward, backward_pass(net, forward, project_late_finish=13)
        )
        self.assertEqual(floats.by_uid()[uid("A")].total_float, -2)
        self.assertTrue(floats.by_uid()[uid("A")].negative)


class FloatTests(unittest.TestCase):
    def test_free_float_is_slack_against_the_successor_not_the_project(self):
        """SEM-FLT-048's shape, stated here so the property has a unit test too."""

        net = network(
            [activity("A", 4), activity("C", 1), activity("E", 1), activity("D", 1)],
            [edge("R1", "A", "D"), edge("R2", "C", "E"), edge("R3", "E", "D")],
        )
        _, _, floats = passes(net)
        rows = floats.by_uid()
        self.assertEqual((rows[uid("C")].total_float, rows[uid("C")].free_float), (2, 0))
        self.assertEqual((rows[uid("E")].total_float, rows[uid("E")].free_float), (2, 2))
        self.assertEqual((rows[uid("D")].total_float, rows[uid("D")].free_float), (0, 0))

    def test_criticality_is_the_threshold_rule_and_nothing_else(self):
        net = network(
            [activity("A", 2), activity("B", 3), activity("C", 1)],
            [edge("R", "A", "B")],
        )
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        strict = float_analysis(net, forward, backward)
        self.assertEqual(strict.critical_activities(), (uid("A"), uid("B")))
        # C has four units of slack, so a four-unit threshold makes it critical.
        relaxed = float_analysis(net, forward, backward, threshold=4)
        self.assertEqual(
            set(relaxed.critical_activities()), {uid("A"), uid("B"), uid("C")}
        )

    def test_a_float_is_working_time_and_not_a_coordinate_difference(self):
        """On a calendar with gaps the two readings differ, and one is reported.

        A one-unit activity that may run anywhere in a two-day window has one
        day of elapsed slack but only the working part of it to spend.
        """

        net = network(
            [activity("A", 1, calendar=BROKEN), activity("B", 9, calendar=BROKEN)],
            horizon=HORIZON,
        )
        forward, backward, floats = passes(net)
        row = floats.by_uid()[uid("A")]
        early = forward.by_uid()[uid("A")]
        elapsed = backward.by_uid()[uid("A")].late_start - early.early_start
        self.assertLess(row.total_float, elapsed)
        self.assertEqual(row.total_float, 8)

    def test_the_two_component_floats_are_reported_separately(self):
        net = network(
            [activity("A", 2, calendar=BROKEN), activity("B", 9, calendar=BROKEN)]
        )
        _, _, floats = passes(net)
        row = floats.by_uid()[uid("A")]
        self.assertEqual(row.total_float, min(row.start_float, row.finish_float))


class MirrorPropertyTests(unittest.TestCase):
    """Relations between the two passes, checked over many generated networks.

    A mirror is the kind of code that is wrong in one direction only, so these
    say what must hold of both passes together rather than checking either
    alone.
    """

    def _networks(self):
        """Chains, fans and diamonds over both calendars and all four types."""

        kinds = list(RelationshipType)
        for calendar in (CONTINUOUS, BROKEN):
            for length in (2, 3, 5):
                for kind in kinds:
                    activities = [
                        activity(f"c{i}", 1 + i % 3, calendar=calendar)
                        for i in range(length)
                    ]
                    edges = [
                        edge(f"e{i}", f"c{i}", f"c{i + 1}", kind, lag=i % 3)
                        for i in range(length - 1)
                    ]
                    yield network(activities, edges)
            # A diamond, where the two branches have different slack.
            yield network(
                [
                    activity("d0", 1, calendar=calendar),
                    activity("d1", 4, calendar=calendar),
                    activity("d2", 1, calendar=calendar),
                    activity("d3", 1, calendar=calendar),
                ],
                [
                    edge("f0", "d0", "d1"),
                    edge("f1", "d0", "d2"),
                    edge("f2", "d1", "d3"),
                    edge("f3", "d2", "d3"),
                ],
            )

    def test_a_late_span_is_as_long_as_the_early_span_it_mirrors(self):
        from sto.core.calendar.arithmetic import working_between

        for net in self._networks():
            forward, backward, _ = passes(net)
            early, later = forward.by_uid(), backward.by_uid()
            for row in net.activities:
                self.assertEqual(
                    working_between(
                        row.calendar,
                        later[row.uid].late_start,
                        later[row.uid].late_finish,
                    ),
                    working_between(
                        row.calendar,
                        early[row.uid].early_start,
                        early[row.uid].early_finish,
                    ),
                    f"late span is a different length on {row.uid}",
                )

    def test_no_late_date_ever_precedes_its_early_date_without_a_constraint(self):
        for net in self._networks():
            forward, backward, floats = passes(net)
            early, later = forward.by_uid(), backward.by_uid()
            for row in net.activities:
                self.assertGreaterEqual(
                    later[row.uid].late_finish, early[row.uid].early_finish, str(row.uid)
                )
                self.assertGreaterEqual(
                    floats.by_uid()[row.uid].total_float, 0, str(row.uid)
                )

    def test_free_float_never_exceeds_total_float_on_a_finish_to_start_network(self):
        """True of FS logic, and only of FS logic -- see the SF case below."""

        for net in self._networks():
            if any(r.type is not RelationshipType.FS for r in net.relationships):
                continue
            _, _, floats = passes(net)
            for row in floats.rows:
                self.assertLessEqual(
                    row.free_float,
                    row.total_float,
                    f"{row.uid} can slip further without delaying anything than at all",
                )

    def test_a_start_to_finish_predecessor_can_have_more_free_float_than_total(self):
        """Not a defect: an SF successor does not care when its predecessor ends.

        SF bounds the successor's *finish* from the predecessor's *start*, so a
        predecessor can slip past the project finish -- consuming total float --
        without moving anything downstream, which leaves free float larger. The
        real files do the same: two of the estate's schedules store a
        ``FreeSlack`` above their ``TotalSlack`` on a handful of rows, so a rule
        forbidding it here would contradict the oracle.
        """

        net = network(
            [activity("A", 1), activity("B", 2)],
            [edge("R", "A", "B", RelationshipType.SF)],
        )
        _, _, floats = passes(net)
        row = floats.by_uid()[uid("A")]
        self.assertEqual((row.total_float, row.free_float), (1, 2))

    def test_something_is_always_critical(self):
        """A schedule whose late finish is its own early finish has a longest path."""

        for net in self._networks():
            _, _, floats = passes(net)
            self.assertTrue(
                floats.critical_activities(),
                "no activity has zero float, so no path drives the finish",
            )

    def test_two_runs_over_one_network_agree(self):
        for net in self._networks():
            forward = forward_pass(net)
            first = backward_pass(net, forward)
            second = backward_pass(net, forward)
            self.assertEqual(first.fingerprint, second.fingerprint)
            self.assertEqual(
                float_analysis(net, forward, first).fingerprint,
                float_analysis(net, forward, second).fingerprint,
            )


class RefusalTests(unittest.TestCase):
    def test_a_forward_pass_over_a_different_network_is_refused(self):
        one = network([activity("A", 2)])
        other = network([activity("B", 2)])
        forward = forward_pass(one)
        with self.assertRaises(BackwardPassError) as caught:
            backward_pass(other, forward)
        self.assertEqual(caught.exception.code, "SCHEDULE_PASS_MISMATCH")

    def test_a_late_date_before_the_project_start_is_reported_not_refused(self):
        """An over-committed schedule has an answer, and the answer is negative."""

        net = network([activity("A", 5)], project_start=10)
        forward = forward_pass(net)
        backward = backward_pass(net, forward, project_late_finish=12)
        self.assertEqual(late(backward, "A"), (7, 12))
        self.assertLess(backward.by_uid()[uid("A")].late_start, net.project_start)

    def test_a_span_with_no_calendar_left_beneath_it_is_refused_by_code(self):
        """The mirror of running out of horizon: there is nothing to answer."""

        late_start = CompiledIntervals.of([(10, HORIZON)])
        net = network([activity("A", 5, calendar=late_start)], project_start=10)
        forward = forward_pass(net)
        with self.assertRaises(BackwardPassError) as caught:
            backward_pass(net, forward, project_late_finish=12)
        self.assertEqual(caught.exception.code, "SCHEDULE_FLOOR_EXCEEDED")

    def test_a_milestone_with_no_calendar_left_beneath_it_is_refused_by_code(self):
        late_start = CompiledIntervals.of([(10, HORIZON)])
        net = network(
            [activity("A", 4, calendar=late_start), activity("M", 0, calendar=late_start)],
            [edge("R", "A", "M")],
            project_start=10,
        )
        forward = forward_pass(net, snap_milestones=True)
        with self.assertRaises(BackwardPassError) as caught:
            backward_pass(net, forward, snap_milestones=True, project_late_finish=5)
        self.assertEqual(caught.exception.code, "SCHEDULE_FLOOR_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
