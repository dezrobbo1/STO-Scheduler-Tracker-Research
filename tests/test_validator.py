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
from sto.core.engine.validate import validate_result
from sto.core.model.enums import RelationshipType

CONTINUOUS = CompiledIntervals.of(((0, 400),))


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-validator/{name}")


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

    def test_a_late_date_before_the_early_one(self):
        _, _, b, _ = _sound()
        rows = list(b.times)
        rows[0] = replace(rows[0], late_start=rows[0].late_start - 20, late_finish=rows[0].late_finish - 20)
        self.assertIn("LATE_BEFORE_EARLY", self._codes(backward=replace(b, times=tuple(rows))))

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

    def test_an_edge_the_dates_do_not_honour(self):
        """The successor pulled back inside its predecessor's lag."""

        _, f, _, _ = _sound()
        times = list(f.times)
        times[1] = replace(times[1], early_start=times[0].early_finish, early_finish=times[0].early_finish + 10)
        self.assertIn(
            "RELATIONSHIP_NOT_HONOURED", self._codes(forward=replace(f, times=tuple(times)))
        )

    def test_free_float_larger_than_total_float_on_one_calendar(self):
        """The shape the float overstated before C2, on the network where the
        theorem holds: one calendar governing everything."""

        _, _, _, fl = _sound()
        rows = list(fl.rows)
        rows[0] = replace(rows[0], free_float=rows[0].total_float + 30)
        self.assertIn(
            "FREE_FLOAT_EXCEEDS_TOTAL", self._codes(floats=replace(fl, rows=tuple(rows)))
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
