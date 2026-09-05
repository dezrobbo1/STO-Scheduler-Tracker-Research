"""The status date and progress, on networks small enough to reason about.

The conformance corpus settles the semantics and the real files settle the
rules about Microsoft Project. What is left for this module is everything
neither of them exercises: the refusals, the defaults, and the behaviours that
only appear on a calendar with gaps in it -- the corpus's cases are all
twenty-four-hour, so every one of its answers would be identical if remaining
work were measured in elapsed time rather than working time.

The eight-hour working day used here is BOILER's shape, so the arithmetic these
tests pin is the arithmetic the real files run.
"""

from __future__ import annotations

import unittest
from uuid import NAMESPACE_URL, UUID, uuid5

from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import (
    FROM_ACTUALS,
    FROM_RELATIONSHIP,
    FROM_STATUS_TIME,
    ForwardPassError,
    Network,
    NetworkError,
    PlannedActivity,
    PlannedRelationship,
    ProgressError,
    ProgressState,
    backward_pass,
    float_analysis,
    forward_pass,
    relationship_binds,
    remaining_bound,
    state_of,
)
from sto.core.model.enums import ConstraintType, ProgressPolicy, RelationshipType

DAY = 86400
CONTINUOUS = CompiledIntervals.of(((0, 100 * DAY),))


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-progress-test/{name}")


def working_days(days: int = 30) -> CompiledIntervals:
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
    *,
    actual_start: int | None = None,
    actual_finish: int | None = None,
    remaining: int | None = None,
    constraint: ConstraintType = ConstraintType.ASAP,
    coordinate: int | None = None,
) -> PlannedActivity:
    return PlannedActivity(
        uid(name),
        duration,
        calendar,
        constraint,
        coordinate,
        actual_start=actual_start,
        actual_finish=actual_finish,
        remaining_duration=remaining,
    )


def link(
    name: str,
    predecessor: str,
    successor: str,
    type: RelationshipType = RelationshipType.FS,
    lag: int = 0,
) -> PlannedRelationship:
    return PlannedRelationship(uid(name), uid(predecessor), uid(successor), type, lag)


def network(*activities, relationships=(), status_time=None, horizon=100 * DAY):
    return Network(
        activities=tuple(activities),
        relationships=tuple(relationships),
        project_start=0,
        horizon=horizon,
        status_time=status_time,
    )


def span(result, name):
    row = result.by_uid()[uid(name)]
    return row.early_start, row.early_finish


class StateTests(unittest.TestCase):
    """Which state the dates put an activity in, and what remains of it."""

    def test_no_dates_is_not_started_with_the_whole_duration_left(self):
        row = activity("A", 10)
        self.assertIs(state_of(row), ProgressState.NOT_STARTED)
        self.assertEqual(row.remaining, 10)

    def test_a_start_alone_is_in_progress(self):
        row = activity("A", 10, actual_start=5, remaining=4)
        self.assertIs(state_of(row), ProgressState.IN_PROGRESS)
        self.assertEqual(row.remaining, 4)

    def test_a_finish_is_complete_and_has_nothing_left(self):
        row = activity("A", 10, actual_start=5, actual_finish=20, remaining=7)
        self.assertIs(state_of(row), ProgressState.COMPLETE)
        # The file said seven; the finish date says none. The date wins.
        self.assertEqual(row.remaining, 0)

    def test_a_declared_remaining_of_zero_is_not_the_same_as_none(self):
        self.assertEqual(activity("A", 10, remaining=0).remaining, 0)
        self.assertEqual(activity("A", 10, remaining=None).remaining, 10)


class RemainingBoundTests(unittest.TestCase):
    """The one policy question, asked directly."""

    def test_not_started_work_obeys_its_logic_under_every_policy(self):
        for policy in ProgressPolicy:
            with self.subTest(policy):
                self.assertEqual(
                    remaining_bound(ProgressState.NOT_STARTED, policy, 40, 90), 40
                )

    def test_retained_logic_takes_the_later_of_logic_and_the_status_date(self):
        for policy in (ProgressPolicy.NONE, ProgressPolicy.RETAINED_LOGIC):
            with self.subTest(policy):
                self.assertEqual(
                    remaining_bound(ProgressState.IN_PROGRESS, policy, 40, 90), 90
                )
                self.assertEqual(
                    remaining_bound(ProgressState.IN_PROGRESS, policy, 140, 90), 140
                )

    def test_progress_override_takes_the_status_date_whatever_the_logic_says(self):
        policy = ProgressPolicy.PROGRESS_OVERRIDE
        self.assertEqual(remaining_bound(ProgressState.IN_PROGRESS, policy, 140, 90), 90)

    def test_without_a_status_date_nothing_is_invented(self):
        for policy in (ProgressPolicy.RETAINED_LOGIC, ProgressPolicy.PROGRESS_OVERRIDE):
            with self.subTest(policy):
                self.assertEqual(
                    remaining_bound(ProgressState.IN_PROGRESS, policy, 40, None), 40
                )

    def test_the_actual_start_is_a_floor_under_every_policy(self):
        # Logic at 40, status at 90, work begun at 500: the remaining work
        # cannot begin before the work did, whatever else holds it.
        for policy in ProgressPolicy:
            if policy is ProgressPolicy.ACTUAL_DATES:
                continue
            with self.subTest(policy):
                self.assertEqual(
                    remaining_bound(ProgressState.IN_PROGRESS, policy, 40, 90, 500), 500
                )
                self.assertEqual(
                    remaining_bound(ProgressState.IN_PROGRESS, policy, 40, None, 500), 500
                )

    def test_but_it_does_not_lower_a_later_bound(self):
        self.assertEqual(
            remaining_bound(
                ProgressState.IN_PROGRESS, ProgressPolicy.RETAINED_LOGIC, 40, 90, 10
            ),
            90,
        )


class ReleasedEdgeTests(unittest.TestCase):
    """Which edges the progress policy releases, asked directly."""

    def test_only_override_with_a_status_time_releases_anything(self):
        for policy in (ProgressPolicy.NONE, ProgressPolicy.RETAINED_LOGIC):
            with self.subTest(policy):
                self.assertTrue(relationship_binds(policy, ProgressState.IN_PROGRESS, 100))
        self.assertTrue(
            relationship_binds(ProgressPolicy.PROGRESS_OVERRIDE, ProgressState.IN_PROGRESS, None)
        )

    def test_and_only_for_a_successor_that_is_under_way(self):
        policy = ProgressPolicy.PROGRESS_OVERRIDE
        self.assertFalse(relationship_binds(policy, ProgressState.IN_PROGRESS, 100))
        self.assertTrue(relationship_binds(policy, ProgressState.NOT_STARTED, 100))
        self.assertTrue(relationship_binds(policy, ProgressState.COMPLETE, 100))


class RemainingWorkOnAWorkingCalendarTests(unittest.TestCase):
    """Remaining work is working time, which only a calendar with gaps shows."""

    def setUp(self):
        self.calendar = working_days()

    def test_remaining_duration_is_consumed_on_the_activity_calendar(self):
        # Started on day zero, six working hours left, status date at the start
        # of day three. Six hours spans the lunch break, so the forecast finish
        # is at fifteen hundred, not fourteen: an elapsed reading would be an
        # hour early.
        status = 3 * DAY + 8 * 3600
        result = forward_pass(
            network(
                activity(
                    "A",
                    8 * 3600,
                    self.calendar,
                    actual_start=8 * 3600,
                    remaining=6 * 3600,
                ),
                status_time=status,
            )
        )
        row = result.by_uid()[uid("A")]
        self.assertEqual(row.early_start, 8 * 3600)
        self.assertEqual(row.remaining_start, status)
        self.assertEqual(row.early_finish, 3 * DAY + 15 * 3600)

    def test_the_actual_start_is_kept_even_when_it_is_not_working_time(self):
        # Work reported as begun at midnight is still reported as begun at
        # midnight. Snapping it into the calendar would be the engine editing a
        # fact it was given.
        result = forward_pass(
            network(
                activity(
                    "A", 4 * 3600, self.calendar, actual_start=0, remaining=4 * 3600
                ),
                status_time=DAY + 8 * 3600,
            )
        )
        self.assertEqual(result.by_uid()[uid("A")].early_start, 0)

    def test_a_completed_activity_ignores_the_calendar_entirely(self):
        # Actuals that span a weekend, a lunch break and a night: kept exactly.
        result = forward_pass(
            network(
                activity(
                    "A",
                    4 * 3600,
                    self.calendar,
                    actual_start=0,
                    actual_finish=5 * DAY + 3600,
                )
            )
        )
        self.assertEqual(span(result, "A"), (0, 5 * DAY + 3600))
        self.assertEqual(result.by_uid()[uid("A")].source, FROM_ACTUALS)


class ActualStartFloorTests(unittest.TestCase):
    """Remaining work never begins before the work did.

    The shape of the one in-progress row in the estate: a status date too
    stale to use, an actual start weeks before the project start, and a logic
    bound -- the project start itself -- that would otherwise place the
    remaining span three weeks after the work began. Microsoft Project placed
    that row's remaining work from its actual start, and so does this pass.
    """

    def test_with_no_status_date_the_remaining_work_follows_the_actual_start(self):
        result = forward_pass(
            network(activity("A", 40, actual_start=500, remaining=10))
        )
        row = result.by_uid()[uid("A")]
        self.assertEqual((row.early_start, row.remaining_start, row.early_finish), (500, 500, 510))
        self.assertEqual(row.source, FROM_ACTUALS)

    def test_a_status_date_before_the_actual_start_does_not_pull_it_back(self):
        result = forward_pass(
            network(activity("A", 40, actual_start=500, remaining=10), status_time=100)
        )
        row = result.by_uid()[uid("A")]
        self.assertEqual((row.remaining_start, row.early_finish), (500, 510))
        self.assertEqual(row.source, FROM_ACTUALS)

    def test_a_project_start_after_the_actual_start_is_not_a_bound_on_started_work(self):
        net = Network(
            activities=(activity("A", 40, actual_start=500, remaining=10),),
            project_start=2000,
            horizon=100 * DAY,
        )
        row = forward_pass(net).by_uid()[uid("A")]
        self.assertEqual((row.remaining_start, row.early_finish), (500, 510))

    def test_a_predecessor_that_finished_before_the_work_began_did_not_hold_it(self):
        result = forward_pass(
            network(
                activity("A", 100),
                activity("B", 40, actual_start=500, remaining=10),
                relationships=(link("R1", "A", "B"),),
            )
        )
        row = result.by_uid()[uid("B")]
        self.assertEqual(row.remaining_start, 500)
        self.assertIsNone(row.driving_relationship_uid)
        self.assertEqual(result.driving_relationships(), ())

    def test_successors_read_a_forecast_finish_that_is_after_the_actual_start(self):
        result = forward_pass(
            network(
                activity("A", 40, actual_start=500, remaining=10),
                activity("B", 5),
                relationships=(link("R1", "A", "B"),),
                status_time=100,
            )
        )
        self.assertEqual(span(result, "B"), (510, 515))


class SourceTests(unittest.TestCase):
    """What the pass says held each activity, which is what a planner acts on."""

    def test_remaining_work_held_by_the_status_date_says_so(self):
        result = forward_pass(
            network(
                activity("A", 40, actual_start=0, remaining=10),
                status_time=100,
            )
        )
        row = result.by_uid()[uid("A")]
        self.assertEqual(row.source, FROM_STATUS_TIME)
        self.assertIsNone(row.driving_relationship_uid)

    def test_remaining_work_held_by_a_predecessor_names_the_relationship(self):
        result = forward_pass(
            network(
                activity("A", 200),
                activity("B", 40, actual_start=0, remaining=10),
                relationships=(link("R1", "A", "B"),),
                status_time=100,
            )
        )
        row = result.by_uid()[uid("B")]
        self.assertEqual(row.source, FROM_RELATIONSHIP)
        self.assertEqual(row.driving_relationship_uid, uid("R1"))
        self.assertEqual(row.remaining_start, 200)

    def test_progress_override_reports_no_driver_at_all(self):
        result = forward_pass(
            network(
                activity("A", 200),
                activity("B", 40, actual_start=0, remaining=10),
                relationships=(link("R1", "A", "B"),),
                status_time=100,
            ),
            progress_policy=ProgressPolicy.PROGRESS_OVERRIDE,
        )
        row = result.by_uid()[uid("B")]
        self.assertIsNone(row.driving_relationship_uid)
        self.assertEqual(row.remaining_start, 100)
        self.assertEqual(result.driving_relationships(), ())


class UnstartedWorkTests(unittest.TestCase):
    """The status date does not move work nobody has touched."""

    def test_an_untouched_activity_is_not_floored_at_the_status_date(self):
        result = forward_pass(network(activity("A", 10), status_time=500))
        self.assertEqual(span(result, "A"), (0, 10))

    def test_it_is_floored_when_the_file_constrains_it(self):
        result = forward_pass(
            network(
                activity("A", 10, constraint=ConstraintType.SNET, coordinate=500),
                status_time=500,
            )
        )
        self.assertEqual(span(result, "A"), (500, 510))

    def test_a_declared_remaining_duration_shortens_untouched_work(self):
        result = forward_pass(network(activity("A", 10, remaining=4)))
        self.assertEqual(span(result, "A"), (0, 4))


class RefusalTests(unittest.TestCase):
    """Progress a pass could only guess at is refused by code."""

    def _refuses(self, code, **kwargs):
        with self.assertRaises(ForwardPassError) as raised:
            forward_pass(network(activity("A", 10, **kwargs)))
        self.assertEqual(raised.exception.code, code)

    def test_a_finish_without_a_start(self):
        self._refuses("SCHEDULE_ACTUAL_FINISH_WITHOUT_START", actual_finish=50)

    def test_a_finish_before_its_own_start(self):
        self._refuses("SCHEDULE_ACTUALS_INVERTED", actual_start=50, actual_finish=20)

    def test_a_negative_remaining_duration(self):
        self._refuses("SCHEDULE_REMAINING_NEGATIVE", remaining=-1)

    def test_started_work_that_does_not_say_what_is_left(self):
        # An untouched activity has all of its duration left; one under way
        # may have consumed any part of it, and the whole duration again would
        # be a forecast nobody reported. Every real file and every corpus case
        # that reports a start reports what is left, so this is refused.
        self._refuses("SCHEDULE_REMAINING_UNKNOWN", actual_start=5)

    def test_but_untouched_work_still_has_its_whole_duration_left(self):
        result = forward_pass(network(activity("A", 10)))
        self.assertEqual(span(result, "A"), (0, 10))

    def test_a_status_date_outside_the_window(self):
        with self.assertRaises(ForwardPassError) as raised:
            forward_pass(network(activity("A", 10), status_time=-5))
        self.assertEqual(raised.exception.code, "SCHEDULE_STATUS_TIME_INVALID")

    def test_the_actual_dates_policy_is_refused_when_it_can_bite(self):
        with self.assertRaises(ProgressError) as raised:
            forward_pass(
                network(activity("A", 10, actual_start=0, remaining=4), status_time=5),
                progress_policy=ProgressPolicy.ACTUAL_DATES,
            )
        self.assertEqual(raised.exception.code, "PROGRESS_POLICY_NOT_EVIDENCED")

    def test_but_not_on_a_schedule_that_carries_no_progress(self):
        # The policy is a project-level setting a planner may have flipped years
        # ago. With nothing to act on it must not stop the file scheduling.
        result = forward_pass(
            network(activity("A", 10), status_time=5),
            progress_policy=ProgressPolicy.ACTUAL_DATES,
        )
        self.assertEqual(span(result, "A"), (0, 10))


class ConstraintsOnStartedWorkTests(unittest.TestCase):
    """A constraint on work that has begun is reported, not applied."""

    def _deferred(self, constraint, **kwargs):
        result = forward_pass(
            network(
                activity("A", 10, constraint=constraint, coordinate=50, **kwargs),
                status_time=10,
            )
        )
        return result, [
            row.type for row in result.deferred_constraints if row.activity_uid == uid("A")
        ]

    def test_a_finish_constraint_on_in_progress_work_is_carried_not_applied(self):
        for constraint in (ConstraintType.FNET, ConstraintType.MFO):
            with self.subTest(constraint):
                result, deferred = self._deferred(
                    constraint, actual_start=1, remaining=10
                )
                self.assertEqual(deferred, [constraint])
                # Placed on its actuals and the status date, not the intention.
                self.assertEqual(result.by_uid()[uid("A")].early_finish, 20)

    def test_a_start_constraint_on_complete_work_is_carried_too(self):
        _, deferred = self._deferred(
            ConstraintType.MSO, actual_start=1, actual_finish=8
        )
        self.assertEqual(deferred, [ConstraintType.MSO])

    def test_an_as_soon_as_possible_row_reports_nothing(self):
        _, deferred = self._deferred(ConstraintType.ASAP, actual_start=1, remaining=10)
        self.assertEqual(deferred, [])


class OverrideReachesTheBackwardPassTests(unittest.TestCase):
    """An edge the forward pass released is released going back and in the float.

    A two-hundred-unit predecessor of work already under way from the status
    date. Under progress override the successor's remaining ten units run from
    one hundred and the project finishes at two hundred; if the backward pass
    still walked the edge it would want the predecessor finished by one
    hundred and ninety, which the calendar cannot hold, and refuse a schedule
    the forward pass had just answered.
    """

    def _network(self):
        return network(
            activity("A", 200),
            activity("B", 40, actual_start=50, remaining=10),
            relationships=(link("R1", "A", "B"),),
            status_time=100,
        )

    def _passes(self, policy):
        net = self._network()
        forward = forward_pass(net, progress_policy=policy)
        backward = backward_pass(net, forward, progress_policy=policy)
        return forward, backward, float_analysis(net, forward, backward)

    def test_under_override_the_edge_is_released_in_both_directions(self):
        forward, backward, floats = self._passes(ProgressPolicy.PROGRESS_OVERRIDE)
        self.assertEqual(span(forward, "B"), (50, 110))
        self.assertEqual(forward.project_finish, 200)
        self.assertEqual(backward.overridden_relationships, (uid("R1"),))
        late = backward.by_uid()[uid("A")]
        self.assertEqual((late.late_start, late.late_finish), (0, 200))
        self.assertEqual(floats.by_uid()[uid("A")].total_float, 0)
        # Free float is measured against the project finish, not the successor
        # the policy says this activity no longer holds.
        self.assertEqual(floats.by_uid()[uid("A")].free_float, 0)
        self.assertEqual(floats.by_uid()[uid("B")].total_float, 90)

    def test_under_retained_logic_the_edge_binds_in_both_directions(self):
        forward, backward, floats = self._passes(ProgressPolicy.RETAINED_LOGIC)
        self.assertEqual(span(forward, "B"), (50, 210))
        self.assertEqual(backward.overridden_relationships, ())
        late = backward.by_uid()[uid("A")]
        self.assertEqual((late.late_start, late.late_finish), (0, 200))
        self.assertEqual(floats.by_uid()[uid("A")].free_float, 0)

    def test_a_backward_pass_that_still_walked_the_edge_would_refuse(self):
        # The defect this class exists to prevent, reproduced: the forward pass
        # released the edge and a backward pass under the other policy walks
        # it, wants the predecessor done by one hundred and ninety, and the
        # calendar cannot hold that. The caller passes one policy to both.
        net = self._network()
        forward = forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        with self.assertRaises(NetworkError) as raised:
            backward_pass(net, forward, progress_policy=ProgressPolicy.RETAINED_LOGIC)
        self.assertEqual(raised.exception.code, "SCHEDULE_FLOOR_EXCEEDED")


class CompletedWorkAndCriticalityTests(unittest.TestCase):
    """The two rules the natively recalculated files settled, in miniature."""

    def _analysis(self):
        net = network(
            activity("A", 40, actual_start=0, actual_finish=40),
            activity("B", 40),
            relationships=(link("R1", "A", "B"),),
        )
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        return net, forward, backward, float_analysis(net, forward, backward)

    def test_a_completed_activity_takes_its_actual_dates_in_both_passes(self):
        _, forward, backward, _ = self._analysis()
        self.assertEqual(span(forward, "A"), (0, 40))
        late = backward.by_uid()[uid("A")]
        self.assertEqual((late.late_start, late.late_finish), (0, 40))

    def test_it_has_no_float_and_is_still_not_critical(self):
        _, _, _, floats = self._analysis()
        row = floats.by_uid()[uid("A")]
        self.assertEqual(row.total_float, 0)
        self.assertTrue(row.complete)
        self.assertFalse(row.critical)

    def test_while_the_unfinished_successor_on_the_same_path_is_critical(self):
        _, _, _, floats = self._analysis()
        row = floats.by_uid()[uid("B")]
        self.assertEqual(row.total_float, 0)
        self.assertFalse(row.complete)
        self.assertTrue(row.critical)


class DeterminismTests(unittest.TestCase):
    """Two runs of a progressed schedule agree, fingerprint included."""

    def _network(self):
        """Out of sequence: B is under way while its predecessor A is not done.

        That is the only shape the two policies disagree about, so it is the
        shape the fingerprint test has to use -- on anything simpler the two
        answers coincide and the assertion would pass for the wrong reason.
        """

        return network(
            activity("A", 10 * 3600, working_days(), actual_start=0, remaining=8 * 3600),
            activity("B", 6 * 3600, working_days(), actual_start=3600, remaining=2 * 3600),
            relationships=(link("R1", "A", "B"),),
            status_time=2 * DAY + 8 * 3600,
        )

    def test_the_fingerprint_is_stable_across_runs(self):
        first = forward_pass(self._network())
        second = forward_pass(self._network())
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_the_policy_changes_the_fingerprint(self):
        retained = forward_pass(self._network())
        override = forward_pass(
            self._network(), progress_policy=ProgressPolicy.PROGRESS_OVERRIDE
        )
        self.assertNotEqual(retained.fingerprint, override.fingerprint)

    def test_the_state_changes_the_fingerprint(self):
        # The same two dates, once as a plan and once as a fact. Criticality
        # treats them differently, so the fingerprint must too.
        planned = forward_pass(network(activity("A", 10)))
        done = forward_pass(network(activity("A", 10, actual_start=0, actual_finish=10)))
        self.assertEqual(span(planned, "A"), span(done, "A"))
        self.assertNotEqual(planned.fingerprint, done.fingerprint)


if __name__ == "__main__":
    unittest.main()
