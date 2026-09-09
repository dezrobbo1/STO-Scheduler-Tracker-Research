"""The independent check, and proof that it catches things (slice S6).

A validator that never fires is worth nothing, so half of this file corrupts a
sound result in one specific way and asserts the code that comes back. The
other half runs it over every executable corpus case, where a violation would
mean the engine had contradicted itself on a case whose answer is pinned.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid5

from conformance_fixture import _build_network, _load, _progress_policy

from sto import conformance
from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import (
    Network,
    PlannedActivity,
    PlannedRelationship,
    backward_pass,
    float_analysis,
    forward_pass,
)
from sto.core.engine.progress import ProgressState
from sto.core.engine.validate import validate_result
from sto.core.model.enums import ConstraintType, ProgressPolicy, RelationshipType

CONTINUOUS = CompiledIntervals.of(((0, 400),))


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-validator/{name}")


def network(*activities, relationships=(), project_start=0, horizon=400, status_time=None):
    return Network(
        activities=tuple(activities),
        relationships=tuple(relationships),
        project_start=project_start,
        horizon=horizon,
        status_time=status_time,
    )


def activity(name, duration, calendar=CONTINUOUS, **fields):
    return PlannedActivity(uid(name), duration, calendar, **fields)


def _sound():
    """A two-activity network and its result, with nothing wrong with it."""

    net = Network(
        activities=(
            PlannedActivity(uid("A"), 10, CONTINUOUS),
            PlannedActivity(uid("B"), 10, CONTINUOUS),
        ),
        relationships=(
            PlannedRelationship(uid("R"), uid("A"), uid("B"), RelationshipType.FS, 5, CONTINUOUS),
        ),
        project_start=0,
        horizon=400,
    )
    forward = forward_pass(net)
    backward = backward_pass(net, forward)
    return net, forward, backward, float_analysis(net, forward, backward)


class ASoundResultPassesTests(unittest.TestCase):
    def test_nothing_is_reported(self):
        self.assertEqual(validate_result(*_sound()), ())


class ACorruptedResultIsCaughtTests(unittest.TestCase):
    """One thing wrong at a time, and the code that comes back for it."""

    def _codes(self, *, forward=None, backward=None, floats=None):
        net, f, b, fl = _sound()
        report = validate_result(net, forward or f, backward or b, floats or fl)
        return {row.code for row in report}

    def test_a_span_that_does_not_consume_its_duration(self):
        _, f, _, _ = _sound()
        times = list(f.times)
        times[0] = replace(times[0], early_finish=times[0].early_finish + 1)
        self.assertIn(
            "EARLY_SPAN_WRONG_LENGTH", self._codes(forward=replace(f, times=tuple(times)))
        )

    def test_a_span_that_runs_backwards(self):
        _, f, _, _ = _sound()
        times = list(f.times)
        times[0] = replace(times[0], early_finish=times[0].early_start - 1)
        self.assertIn("EARLY_SPAN_INVERTED", self._codes(forward=replace(f, times=tuple(times))))

    def test_a_total_float_that_is_not_the_gap_between_the_spans(self):
        _, _, _, fl = _sound()
        rows = list(fl.rows)
        rows[0] = replace(rows[0], total_float=rows[0].total_float + 60)
        self.assertIn("TOTAL_FLOAT_MISMATCH", self._codes(floats=replace(fl, rows=tuple(rows))))

    def test_a_criticality_flag_that_disagrees_with_its_own_float(self):
        _, _, _, fl = _sound()
        rows = list(fl.rows)
        rows[0] = replace(rows[0], critical=not rows[0].critical)
        self.assertIn("CRITICALITY_MISMATCH", self._codes(floats=replace(fl, rows=tuple(rows))))

    def test_a_late_span_moved_off_the_float_it_reports(self):
        """What the dropped ordering rule was really catching.

        A late span dragged backwards is not a structural fault -- that shape
        is negative float, and a sound overcommitted schedule has it. What it
        is, is a disagreement with the number the result reports, and the float
        measurement says so precisely.
        """

        _, _, b, _ = _sound()
        rows = list(b.times)
        rows[0] = replace(
            rows[0], late_start=rows[0].late_start - 20, late_finish=rows[0].late_finish - 20
        )
        codes = self._codes(backward=replace(b, times=tuple(rows)))
        self.assertIn("TOTAL_FLOAT_MISMATCH", codes)
        self.assertIn("FINISH_FLOAT_MISMATCH", codes)

    def test_an_edge_the_dates_do_not_honour(self):
        """The successor pulled back inside its predecessor's lag."""

        _, f, _, _ = _sound()
        times = list(f.times)
        times[1] = replace(times[1], early_start=times[0].early_finish, early_finish=times[0].early_finish + 10)
        self.assertIn(
            "RELATIONSHIP_NOT_HONOURED", self._codes(forward=replace(f, times=tuple(times)))
        )

    def test_free_float_that_would_move_a_successor(self):
        """The shape the float overstated before C2.

        Checked by applying the number rather than bounding it: an activity
        with this much free float would move its successor, so the slack it
        reports is not slack.
        """

        _, _, _, fl = _sound()
        rows = list(fl.rows)
        rows[0] = replace(rows[0], free_float=rows[0].total_float + 30)
        self.assertIn("FREE_FLOAT_TOO_LARGE", self._codes(floats=replace(fl, rows=tuple(rows))))

    def test_free_float_smaller_than_the_room_that_is_there(self):
        """The half a one-sided bound could never catch."""

        _, _, _, fl = _sound()
        rows = list(fl.rows)
        rows[0] = replace(rows[0], free_float=rows[0].free_float - 1)
        self.assertIn("FREE_FLOAT_TOO_SMALL", self._codes(floats=replace(fl, rows=tuple(rows))))


class TheChecksTheFirstVersionMissedTests(unittest.TestCase):
    """One corruption per gap the slice's own review found."""

    def _codes(self, net, forward, backward, floats, **kwargs):
        return {row.code for row in validate_result(net, forward, backward, floats, **kwargs)}

    def test_a_row_answered_twice_is_not_collapsed_into_one(self):
        net, f, b, fl = _sound()
        doubled = replace(f, times=f.times + (f.times[0],))
        self.assertIn("FORWARD_DUPLICATE_ACTIVITY", self._codes(net, doubled, b, fl))

    def test_a_missing_float_row_is_reported_rather_than_raised(self):
        net, f, b, fl = _sound()
        short = replace(fl, rows=fl.rows[1:])
        codes = self._codes(net, f, b, short)
        self.assertIn("FLOAT_MISSING_ACTIVITY", codes)

    def test_a_completed_row_still_has_its_float_and_flag_checked(self):
        """Only the duration exemption belongs to completed work."""

        net = network(
            activity("A", 10, actual_start=0, actual_finish=10),
            status_time=20,
        )
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        self.assertEqual(validate_result(net, forward, backward, floats), ())
        rows = list(floats.rows)
        rows[0] = replace(rows[0], critical=True)
        self.assertIn(
            "CRITICALITY_MISMATCH",
            self._codes(net, forward, backward, replace(floats, rows=tuple(rows))),
        )

    def test_the_threshold_comes_from_the_analysis_that_set_the_flags(self):
        """A file with a declared threshold is sound, not a wall of mismatches."""

        net, f, b, _ = _sound()
        generous = float_analysis(net, f, b, threshold=3600)
        self.assertEqual(validate_result(net, f, b, generous), ())

    def test_a_component_float_can_not_be_anything_it_likes(self):
        net, f, b, fl = _sound()
        rows = list(fl.rows)
        rows[0] = replace(rows[0], start_float=rows[0].start_float + 45)
        self.assertIn(
            "START_FLOAT_MISMATCH", self._codes(net, f, b, replace(fl, rows=tuple(rows)))
        )

    def test_a_span_that_ignores_its_own_constraint(self):
        net = network(
            activity(
                "A",
                10,
                constraint_type=ConstraintType.SNET,
                constraint_coordinate=100,
            ),
        )
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        self.assertEqual(validate_result(net, forward, backward, floats), ())
        times = list(forward.times)
        times[0] = replace(times[0], early_start=0, early_finish=10)
        moved = replace(forward, times=tuple(times))
        self.assertIn("CONSTRAINT_NOT_HONOURED", self._codes(net, moved, backward, floats))

    def test_a_successor_pulled_before_its_anchor_inside_a_gap(self):
        """Working time is blind to order; a zero lag is a coordinate."""

        gapped = CompiledIntervals.of(((0, 5), (20, 400)))
        net = network(
            activity("A", 5, gapped),
            activity("M", 0, gapped),
            relationships=(
                PlannedRelationship(uid("R"), uid("A"), uid("M"), RelationshipType.FS, 0, gapped),
            ),
        )
        forward = forward_pass(net, snap_milestones=False)
        backward = backward_pass(net, forward, snap_milestones=False)
        floats = float_analysis(net, forward, backward)
        self.assertEqual(validate_result(net, forward, backward, floats), ())
        times = list(forward.times)
        moved = replace(times[1], early_start=times[0].early_finish - 1, early_finish=times[0].early_finish - 1)
        times[1] = moved
        self.assertIn(
            "RELATIONSHIP_NOT_HONOURED",
            self._codes(net, replace(forward, times=tuple(times)), backward, floats),
        )

    def test_remaining_work_moved_below_its_floor(self):
        net = network(
            activity("A", 20, actual_start=0, remaining_duration=5),
            status_time=50,
        )
        forward = forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        clean = validate_result(
            net, forward, backward, floats, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE
        )
        self.assertEqual(clean, ())
        times = list(forward.times)
        times[0] = replace(times[0], remaining_start=10, early_finish=15)
        self.assertIn(
            "REMAINING_START_BEFORE_ITS_FLOOR",
            self._codes(
                net,
                replace(forward, times=tuple(times)),
                backward,
                floats,
                progress_policy=ProgressPolicy.PROGRESS_OVERRIDE,
            ),
        )


class TheChecksTheSecondPassFoundTests(unittest.TestCase):
    """One corruption per gap the second review of this slice found.

    All of them are the same kind of hole: the validator measured what a
    result computed and never asked whether the result's own claims about
    itself -- its state, its actuals, the edge it names as its driver -- were
    true.
    """

    def _codes(self, net, forward, backward, floats, **kwargs):
        return {row.code for row in validate_result(net, forward, backward, floats, **kwargs)}

    def _progressed(self, policy):
        net = network(
            activity("A", 20, actual_start=0, remaining_duration=5),
            status_time=50,
        )
        forward = forward_pass(net, progress_policy=policy)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        return net, forward, backward, floats

    def test_retained_logic_raises_remaining_work_to_the_status_date_too(self):
        """Both policies apply the floor; only one of them was checked."""

        net, f, b, fl = self._progressed(ProgressPolicy.RETAINED_LOGIC)
        self.assertEqual(validate_result(net, f, b, fl), ())
        times = list(f.times)
        times[0] = replace(times[0], remaining_start=10, early_finish=15)
        self.assertIn(
            "REMAINING_START_BEFORE_ITS_FLOOR",
            self._codes(net, replace(f, times=tuple(times)), b, fl),
        )

    def test_the_policy_comes_from_the_pass_that_ran(self):
        """A sound override result read as a broken retained-logic one."""

        net, f, b, fl = self._progressed(ProgressPolicy.PROGRESS_OVERRIDE)
        self.assertEqual(validate_result(net, f, b, fl), ())
        self.assertIn(
            "SCHEDULE_POLICY_MISMATCH",
            self._codes(net, f, b, fl, progress_policy=ProgressPolicy.RETAINED_LOGIC),
        )

    def test_a_root_moved_behind_the_project_start(self):
        net = network(activity("A", 10), project_start=100)
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        self.assertEqual(validate_result(net, forward, backward, floats), ())

        times = list(forward.times)
        times[0] = replace(times[0], early_start=50, early_finish=60)
        late = list(backward.times)
        late[0] = replace(late[0], late_start=50, late_finish=60)
        self.assertIn(
            "EARLY_START_BEFORE_PROJECT_START",
            self._codes(
                net,
                replace(forward, times=tuple(times)),
                replace(backward, times=tuple(late)),
                floats,
            ),
        )

    def test_a_row_that_reports_the_wrong_state(self):
        net, f, b, fl = _sound()
        times = list(f.times)
        times[0] = replace(times[0], state=ProgressState.COMPLETE)
        self.assertIn(
            "PROGRESS_STATE_MISMATCH", self._codes(net, replace(f, times=tuple(times)), b, fl)
        )

    def test_a_float_row_that_claims_the_work_is_finished(self):
        net, f, b, fl = _sound()
        rows = list(fl.rows)
        rows[0] = replace(rows[0], complete=True)
        self.assertIn(
            "COMPLETE_FLAG_MISMATCH", self._codes(net, f, b, replace(fl, rows=tuple(rows)))
        )

    def test_completed_work_moved_off_the_dates_it_reports(self):
        """The duration exemption is not a licence to rewrite history."""

        net = network(activity("A", 10, actual_start=0, actual_finish=10), status_time=20)
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        self.assertEqual(validate_result(net, forward, backward, floats), ())
        times = list(forward.times)
        times[0] = replace(times[0], early_start=20, early_finish=30)
        codes = self._codes(net, replace(forward, times=tuple(times)), backward, floats)
        self.assertIn("COMPLETED_START_NOT_ITS_ACTUAL", codes)
        self.assertIn("COMPLETED_FINISH_NOT_ITS_ACTUAL", codes)

    def test_work_under_way_moved_off_the_start_it_had(self):
        net, f, b, fl = self._progressed(ProgressPolicy.RETAINED_LOGIC)
        times = list(f.times)
        times[0] = replace(times[0], early_start=7)
        self.assertIn(
            "STARTED_WORK_MOVED_OFF_ITS_ACTUAL",
            self._codes(net, replace(f, times=tuple(times)), b, fl),
        )

    def test_a_row_that_names_an_edge_it_is_not_on(self):
        """The forward driver is an edge *into* the row; the backward one out."""

        net, f, b, fl = _sound()
        stranger = uid("nowhere")
        times = list(f.times)
        times[1] = replace(times[1], driving_relationship_uid=stranger)
        self.assertIn(
            "FORWARD_DRIVER_NOT_INCIDENT", self._codes(net, replace(f, times=tuple(times)), b, fl)
        )
        late = list(b.times)
        late[0] = replace(late[0], driving_relationship_uid=stranger)
        self.assertIn(
            "BACKWARD_DRIVER_NOT_INCIDENT",
            self._codes(net, f, replace(b, times=tuple(late)), fl),
        )

class TheChecksTheThirdPassFoundTests(unittest.TestCase):
    """Sound results the validator was rejecting, and claims it never read.

    Every one of these is the same mistake in the other direction from the
    earlier passes: a rule stated more strongly than the engine's own
    behaviour, so a correct answer came back as a violation.
    """

    def _codes(self, net, forward, backward, floats, **kwargs):
        return {row.code for row in validate_result(net, forward, backward, floats, **kwargs)}

    def test_an_overcommitted_schedule_is_sound_not_inverted(self):
        """A late span before its early one is what negative float is."""

        net = network(activity("A", 5), project_start=10)
        forward = forward_pass(net)
        backward = backward_pass(net, forward, project_late_finish=13)
        floats = float_analysis(net, forward, backward)

        row = floats.by_uid()[uid("A")]
        self.assertEqual(row.total_float, -2)
        self.assertTrue(row.negative)
        self.assertLess(backward.by_uid()[uid("A")].late_start, forward.by_uid()[uid("A")].early_start)
        self.assertEqual(validate_result(net, forward, backward, floats), ())

    def test_a_finish_no_later_than_is_asked_of_the_late_span(self):
        """The forward pass leaves the early finish past an FNLT it cannot meet.

        That is the shortfall, carried as negative float, and it is the
        backward pass that lowers the late finish to the constraint. Asking
        the early span rejected the pass's own documented behaviour.
        """

        net = network(
            activity("A", 2),
            activity("B", 3, constraint_type=ConstraintType.FNLT, constraint_coordinate=14),
            relationships=(
                PlannedRelationship(uid("R"), uid("A"), uid("B"), RelationshipType.FS, 0, CONTINUOUS),
            ),
        )
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        self.assertEqual(validate_result(net, forward, backward, floats), ())

        late = list(backward.times)
        index = next(i for i, row in enumerate(late) if row.uid == uid("B"))
        late[index] = replace(late[index], late_finish=late[index].late_finish + 20)
        self.assertIn(
            "CONSTRAINT_NOT_HONOURED",
            self._codes(net, forward, replace(backward, times=tuple(late)), floats),
        )

    def test_an_edge_a_hard_constraint_displaced_is_not_asked_to_hold(self):
        """A must-start-on date wins against precedence, and says what it broke."""

        net = network(
            activity("A", 4),
            activity("B", 2, constraint_type=ConstraintType.MSO, constraint_coordinate=12),
            relationships=(
                PlannedRelationship(uid("R"), uid("A"), uid("B"), RelationshipType.FS, 0, CONTINUOUS),
            ),
            project_start=10,
        )
        forward = forward_pass(net)
        self.assertTrue(
            forward.constraint_violations, "the fixture no longer displaces its logic"
        )
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        self.assertEqual(validate_result(net, forward, backward, floats), ())

    def test_the_project_coordinates_are_read_too(self):
        """Three numbers outside every row, taken on trust until now."""

        net, f, b, fl = _sound()
        self.assertIn(
            "PROJECT_START_MISMATCH",
            self._codes(net, replace(f, project_start=f.project_start - 5), b, fl),
        )
        self.assertIn(
            "PROJECT_FINISH_MISMATCH",
            self._codes(net, replace(f, project_finish=f.project_finish + 5), b, fl),
        )
        self.assertIn(
            "PROJECT_LATE_FINISH_MISMATCH",
            self._codes(
                net, f, b, replace(fl, project_late_finish=fl.project_late_finish + 5)
            ),
        )

class TheChecksTheFourthPassFoundTests(unittest.TestCase):
    """What the checker took on trust, and one probe that could not answer."""

    def _codes(self, net, forward, backward, floats, **kwargs):
        return {row.code for row in validate_result(net, forward, backward, floats, **kwargs)}

    def test_a_result_from_another_network_is_not_read_as_this_one(self):
        """Both passes hash the network they ran over; nothing compared it."""

        net, f, b, fl = _sound()
        other = replace(net, horizon=net.horizon + 1000)
        codes = self._codes(other, f, b, fl)
        self.assertIn("FORWARD_NETWORK_MISMATCH", codes)
        self.assertIn("BACKWARD_NETWORK_MISMATCH", codes)

    def test_a_free_float_that_can_not_be_applied_at_all(self):
        """Silence from both probes was read as agreement."""

        net, f, b, fl = _sound()
        rows = list(fl.rows)
        rows[0] = replace(rows[0], free_float=-100_000)
        self.assertIn(
            "FREE_FLOAT_UNANSWERABLE", self._codes(net, f, b, replace(fl, rows=tuple(rows)))
        )

    def test_a_completed_late_span_is_pinned_to_its_actuals_too(self):
        """The forward checks did not protect the backward copy of history."""

        net = network(activity("A", 10, actual_start=0, actual_finish=10), status_time=20)
        forward = forward_pass(net)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        self.assertEqual(validate_result(net, forward, backward, floats), ())
        late = list(backward.times)
        late[0] = replace(late[0], late_start=1, late_finish=11)
        codes = self._codes(net, forward, replace(backward, times=tuple(late)), floats)
        self.assertIn("COMPLETED_LATE_START_NOT_ITS_ACTUAL", codes)
        self.assertIn("COMPLETED_LATE_FINISH_NOT_ITS_ACTUAL", codes)

    def test_work_under_way_has_to_say_where_its_remaining_work_begins(self):
        """The coordinate exists for this state, and its absence was invisible."""

        net = network(
            activity("A", 20, actual_start=0, remaining_duration=5), status_time=50
        )
        forward = forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        backward = backward_pass(net, forward)
        floats = float_analysis(net, forward, backward)
        times = list(forward.times)
        times[0] = replace(times[0], remaining_start=None)
        self.assertIn(
            "REMAINING_START_MISSING",
            self._codes(net, replace(forward, times=tuple(times)), backward, floats),
        )

class TheCorpusValidatesTests(unittest.TestCase):
    """Every case the engine runs, checked against itself rather than its answer."""

    def test_no_executable_case_contradicts_itself(self):
        for case_id in conformance.executable_case_ids():
            with self.subTest(case_id):
                case = _load(case_id)
                network, _ = _build_network(case_id, case)
                policy = _progress_policy(case)
                forward = forward_pass(network, progress_policy=policy)
                backward = backward_pass(network, forward)
                floats = float_analysis(network, forward, backward)
                self.assertEqual(
                    validate_result(
                        network, forward, backward, floats, progress_policy=policy
                    ),
                    (),
                )


if __name__ == "__main__":
    unittest.main()
