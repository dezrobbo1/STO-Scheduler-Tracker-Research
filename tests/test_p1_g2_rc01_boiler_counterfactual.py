"""Synthetic pre-result checks for the RC01 diagnostic; no BOILER oracle."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from scripts.evidence import p1_g2_baseline_diagnostics as baseline
from scripts.evidence import p1_g2_rc01_boiler_counterfactual as cf

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2.xml"


def fixture():
    return baseline._load(FIXTURE.read_bytes())


class Rc01BoilerPreResultTests(unittest.TestCase):
    def test_predeclared_evidence_identities_and_exact_baseline_refusal(self):
        inventory, v2 = cf.load_contract()
        self.assertEqual(len(inventory["current_recomputation"]["mismatches"]), 147)
        self.assertEqual(v2["classification"]["verdict"],
                         "V2_ASSIGNMENT_ENVELOPE_SUPPORTED")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-boiler.xml"
            path.write_bytes(FIXTURE.read_bytes())
            with self.assertRaisesRegex(cf.CounterfactualError, "pinned evidence identity"):
                cf.pinned(path, cf.BASE_BYTES, cf.BASE_SHA)

    def test_v2_assignment_envelopes_controls_and_backward_inverse(self):
        schedule = fixture()
        plan, early, late, floats, rows, audit = cf.calculate(schedule)
        expected = {
            "RC01-CASE-A": (8, 17), "RC01-CASE-B": (8, 17),
            "RC01-CASE-C": (8, 12), "RC01-CASE-D": (8, 12),
        }
        for activity in schedule.activities:
            with self.subTest(case=activity.name):
                start, finish, _, _, late_start, late_finish, *_ = rows[activity.uid]
                self.assertEqual((start.hour, finish.hour), expected[activity.name])
                self.assertEqual((late_start.hour, late_finish.hour), expected[activity.name])
        self.assertEqual(cf.validate_diagnostic(schedule, plan, early, late, floats, audit), [])
        self.assertEqual([a["classification"] for a in audit],
                         ["WITHIN_V2_COUNTERFACTUAL_BOUNDARY"] * 4)
        self.assertFalse(audit[-1]["diagnostic_eligible"])

    def test_reversed_declaration_order_does_not_move_envelope(self):
        schedule = fixture()
        initial = cf.calculate(schedule)[4]
        swapped = replace(schedule, assignments=tuple(reversed(schedule.assignments)))
        changed = cf.calculate(swapped)[4]
        self.assertEqual(initial, changed)

    def test_oracle_task_and_assignment_dates_are_not_candidate_inputs(self):
        schedule = fixture()
        initial = cf.calculate(schedule)[4]
        future = datetime(2035, 1, 1, 7)
        activities = tuple(replace(a, source_observations=replace(
            a.source_observations, early_start=future, late_finish=future,
            start=future, finish=future)) for a in schedule.activities)
        assignments = tuple(replace(a, start=future, finish=None)
                            for a in schedule.assignments)
        changed = cf.calculate(replace(schedule, activities=activities,
                                       assignments=assignments))[4]
        self.assertEqual(initial, changed)

    def test_no_eligible_multiresource_is_coordinate_equivalent_to_production(self):
        schedule = fixture()
        d = next(a for a in schedule.activities if a.name == "RC01-CASE-D")
        only = replace(schedule, activities=(d,),
                       assignments=tuple(a for a in schedule.assignments if a.activity_uid == d.uid))
        production = baseline._calculate(only)
        candidate = cf.calculate(only)
        self.assertEqual(candidate[4], production.result)
        self.assertEqual(candidate[1].fingerprint, production.forward.fingerprint)
        self.assertEqual(candidate[2].fingerprint, production.backward.fingerprint)

    def test_unsupported_work_units_and_task_type_fail_closed(self):
        schedule = fixture()
        first = schedule.assignments[0]
        for changed in (
            replace(first, units=replace(first.units, budgeted_permille=0)),
            replace(first, work=replace(first.work, budgeted_seconds=1,
                                        remaining_seconds=1),
                    units=replace(first.units, budgeted_permille=300)),
        ):
            with self.subTest(assignment=changed):
                altered = replace(schedule, assignments=(changed,) + schedule.assignments[1:])
                _, _, _, _, _, audit = cf.calculate(altered)
                self.assertFalse(audit[0]["diagnostic_eligible"])
                self.assertEqual(audit[0]["classification"],
                                 "DIAGNOSTIC_EXTRAPOLATION_REQUIRED")
        from sto.core.model.enums import DurationType
        changed_task = replace(schedule.activities[0], duration_type=DurationType.FIXED_DURATION)
        altered = replace(schedule, activities=(changed_task,) + schedule.activities[1:])
        self.assertFalse(cf.calculate(altered)[5][0]["diagnostic_eligible"])

    def test_wrapper_restores_production_passes_even_when_it_refuses(self):
        original_forward, original_backward = cf.forward._place, cf.backward._place
        with self.assertRaisesRegex(cf.CounterfactualError, "unmeasured envelope rule"):
            with cf._placement({}):
                self.assertIsNot(cf.forward._place, original_forward)
                raise cf.CounterfactualError("unmeasured envelope rule")
        self.assertIs(cf.forward._place, original_forward)
        self.assertIs(cf.backward._place, original_backward)

    def test_cli_rejects_source_output_alias_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "boiler.xml"
            source.write_bytes(b"immutable BOILER copy")
            before = source.read_bytes()
            symlink = source.with_name("linked.xml")
            symlink.symlink_to(source)
            hardlink = source.with_name("hardlinked.xml")
            os.link(source, hardlink)
            protected = (cf.CURRENT_PATH, cf.NATIVE_PATH, FIXTURE, Path(cf.__file__),
                         ROOT / "docs/evidence/p1-g2-rc01-boiler-counterfactual-predeclared-2026-09-28.json")
            unchanged = {path: path.read_bytes() for path in protected}
            for output in (source, source.parent / ".." / source.parent.name / source.name,
                           symlink, hardlink, *protected):
                with self.subTest(output=output):
                    with patch("sys.argv", ["p1_g2_rc01_boiler_counterfactual.py",
                                            str(source), "--output", str(output)]):
                        with self.assertRaisesRegex(ValueError, "aliases"):
                            cf.main()
            self.assertEqual(source.read_bytes(), before)
            for path, content in unchanged.items():
                self.assertEqual(path.read_bytes(), content)

    def test_separate_candidate_replaced_atomically_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xml"
            source.write_bytes(b"immutable")
            candidate = root / "candidate.json"
            candidate.write_text("old")
            cf.current.write_output_safely(candidate, "new\n", {"BOILER baseline": source})
            self.assertEqual(candidate.read_bytes(), b"new\n")
            self.assertEqual(source.read_bytes(), b"immutable")


if __name__ == "__main__":
    unittest.main()
