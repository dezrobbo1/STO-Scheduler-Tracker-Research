"""Independent RC03 elapsed-float cases, with a non-working gap as discriminator.

Units here are synthetic hours.  E works continuously, but the task/project
measurement calendar works 0–4, 8–14, 20–30.  Thus the elapsed and productive
answers cannot coincide by accident.  This does not use customer schedule data.
"""
from __future__ import annotations

from dataclasses import replace
import unittest
from uuid import NAMESPACE_URL, uuid5

from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import (
    Network, PlannedActivity, PlannedRelationship, backward_pass, float_analysis,
    forward_pass, validate_result,
)
from sto.core.model.enums import ConstraintType


WORKING = CompiledIntervals.of(((0, 4), (8, 14), (20, 30)))
CONTINUOUS = CompiledIntervals.of(((0, 30),))
SUCCESSOR = CompiledIntervals.of(((8, 14), (20, 30)))


def uid(name):
    return uuid5(NAMESPACE_URL, f"sto-test/rc03-independent/{name}")


def example(basis="elapsed"):
    # Separate 15-hour path determines the project's late finish; successor
    # starts at 8 after E finishes at 2, leaving six elapsed hours of free float.
    # E's late span is 11–13, leaving eleven elapsed hours of total float.
    e = PlannedActivity(uid("E"), 2, CONTINUOUS if basis == "elapsed" else WORKING,
                        measure_calendar=WORKING, float_basis=basis)
    s = PlannedActivity(uid("S"), 1, SUCCESSOR)
    driver = PlannedActivity(uid("driver"), 15, CONTINUOUS)
    return Network((e, s, driver), (PlannedRelationship(uid("E-S"), e.uid, s.uid),),
                   project_start=0, horizon=30)


def calculate(network, *, threshold=0):
    forward = forward_pass(network)
    backward = backward_pass(network, forward)
    floats = float_analysis(network, forward, backward, threshold=threshold)
    return forward, backward, floats


class IndependentElapsedFloatConformance(unittest.TestCase):
    def test_total_and_free_float_are_elapsed_across_calendar_gap(self):
        network = example()
        forward, backward, floats = calculate(network)
        self.assertEqual((forward.by_uid()[uid("E")].early_start,
                          forward.by_uid()[uid("E")].early_finish), (0, 2))
        self.assertEqual((backward.by_uid()[uid("E")].late_start,
                          backward.by_uid()[uid("E")].late_finish), (11, 13))
        row = floats.by_uid()[uid("E")]
        self.assertEqual((row.start_float, row.finish_float, row.total_float,
                          row.free_float), (11, 11, 11, 6))
        self.assertFalse(row.critical)
        self.assertEqual(validate_result(network, forward, backward, floats), ())

    def test_ordinary_control_keeps_productive_float(self):
        network = example("working")
        forward, backward, floats = calculate(network)
        row = floats.by_uid()[uid("E")]
        self.assertEqual((row.start_float, row.finish_float, row.total_float,
                          row.free_float), (7, 7, 7, 2))
        self.assertEqual(validate_result(network, forward, backward, floats), ())

    def test_negative_elapsed_float_remains_signed(self):
        e = PlannedActivity(uid("negative"), 2, CONTINUOUS,
                            constraint_type=ConstraintType.FNLT,
                            constraint_coordinate=3, measure_calendar=WORKING,
                            float_basis="elapsed")
        network = Network((e,), project_start=8, horizon=30)
        forward, backward, floats = calculate(network)
        self.assertEqual((forward.times[0].early_start, forward.times[0].early_finish),
                         (8, 10))
        self.assertEqual((backward.times[0].late_start, backward.times[0].late_finish),
                         (1, 3))
        row = floats.rows[0]
        self.assertEqual((row.start_float, row.finish_float, row.total_float),
                         (-7, -7, -7))
        self.assertTrue(row.critical)
        self.assertEqual(validate_result(network, forward, backward, floats), ())

    def test_threshold_uses_corrected_total(self):
        network = example()
        self.assertFalse(calculate(network, threshold=10)[2].by_uid()[uid("E")].critical)
        self.assertTrue(calculate(network, threshold=11)[2].by_uid()[uid("E")].critical)

    def test_float_basis_affects_identity_but_not_dates(self):
        elapsed = example()
        working = replace(elapsed, activities=(replace(elapsed.activities[0],
                             float_basis="working"),) + elapsed.activities[1:])
        self.assertEqual(example("working").fingerprint(),
                         "6eaf79eea08801217645aea403bdbde985e9c036b203ec5c4a7ac689d5086c57")
        self.assertNotEqual(elapsed.fingerprint(), working.fingerprint())
        early_a, late_a, floats_a = calculate(elapsed)
        early_b, late_b, floats_b = calculate(working)
        self.assertEqual(early_a.times, early_b.times)
        self.assertEqual(late_a.times, late_b.times)
        self.assertNotEqual(floats_a.by_uid()[uid("E")].total_float,
                            floats_b.by_uid()[uid("E")].total_float)


if __name__ == "__main__":
    unittest.main()
