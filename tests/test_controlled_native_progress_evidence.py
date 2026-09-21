from __future__ import annotations

import json
from pathlib import Path
import unittest

from tests.controlled_native_progress_evidence import (
    BASELINE_MISMATCH,
    DIRECT_CONTROLLED_EDIT,
    ENGINE_NATIVE_AGREEMENT,
    EXPLICIT_EXCLUSION,
    PROJECT_DERIVED_PROGRESS_INPUT,
    RESULT_FIELDS,
    UNCHANGED,
    UNEXPLAINED,
    classify_controlled_transition,
    classify_selected_progress,
    unique_rows,
)
from tests.real_fixture_guard import RECORDED


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/p1-final-native-progress-2026-09-20.json"


def row(**changes: object) -> tuple[object, ...]:
    values = {field: f"same-{field}" for field in RESULT_FIELDS}
    values.update(changes)
    return tuple(values[field] for field in RESULT_FIELDS)


class ControlledNativeProgressEvidenceTests(unittest.TestCase):
    def classify(
        self,
        *,
        before=None,
        native=None,
        base=None,
        control=None,
        recalculated=None,
        exclusions=None,
    ):
        before = {"1": row()} if before is None else before
        native = {"1": row()} if native is None else native
        base = {"1": row()} if base is None else base
        control = {"1": row()} if control is None else control
        recalculated = {"1": row()} if recalculated is None else recalculated
        exclusions = {} if exclusions is None else exclusions
        return classify_controlled_transition(
            before,
            native,
            base,
            control,
            recalculated,
            exclusions,
        )

    def test_unchanged_row_stays_unchanged(self):
        summary = self.classify()
        self.assertEqual(dict(summary.classifications), {UNCHANGED: len(RESULT_FIELDS)})
        self.assertEqual(summary.unexplained_count, 0)

    def test_unchanged_native_value_does_not_hide_a_static_engine_mismatch(self):
        summary = self.classify(
            base={"1": row(late_finish="wrong")},
            control={"1": row(late_finish="wrong")},
            recalculated={"1": row(late_finish="wrong")},
        )
        self.assertEqual(dict(summary.classifications)[BASELINE_MISMATCH], 1)
        self.assertEqual(summary.baseline_mismatches, (("1", "late_finish"),))
        self.assertEqual(summary.unexpected_transition_count, 0)
        self.assertEqual(summary.unexplained_count, 1)

    def test_downstream_engine_native_agreement_is_recognized(self):
        summary = self.classify(
            native={"1": row(finish="moved")},
            control={"1": row(finish="moved")},
            recalculated={"1": row(finish="moved")},
        )
        self.assertEqual(dict(summary.classifications)[ENGINE_NATIVE_AGREEMENT], 1)
        self.assertEqual(summary.unexplained_count, 0)

    def test_seeded_engine_mismatch_is_unexplained(self):
        summary = self.classify(
            native={"1": row(finish="other")},
            control={"1": row(finish="expected")},
            recalculated={"1": row(finish="expected")},
        )
        self.assertEqual(summary.unexplained, (("1", "finish"),))

    def test_changed_edited_row_field_is_not_implicitly_expected(self):
        summary = self.classify(native={"1": row(late_finish="changed")})
        self.assertEqual(summary.unexplained, (("1", "late_finish"),))

    def test_baseline_must_already_agree_before_native_convergence_counts(self):
        summary = self.classify(
            native={"1": row(late_start="native")},
            base={"1": row(late_start="old-engine")},
            control={"1": row(late_start="native")},
            recalculated={"1": row(late_start="native")},
        )
        self.assertEqual(summary.unexplained, (("1", "late_start"),))

    def test_start_finish_do_not_substitute_for_early_fields(self):
        summary = self.classify(
            native={"1": row(start="moved", finish="moved")},
            control={"1": row(start="moved", finish="moved")},
            recalculated={"1": row(start="moved", finish="moved")},
        )
        self.assertEqual(dict(summary.classifications)[ENGINE_NATIVE_AGREEMENT], 2)
        self.assertNotIn(("1", "early_start"), summary.unexplained)
        self.assertNotIn(("1", "early_finish"), summary.unexplained)

    def test_unchanged_excluded_fields_are_explicit_and_changes_are_not_swallowed(self):
        summary = self.classify(
            native={"1": row(), "2": row(start="changed")},
            before={"1": row(), "2": row()},
            base={},
            control={},
            recalculated={},
            exclusions={"1": "INACTIVE", "2": "INACTIVE"},
        )
        self.assertEqual(dict(summary.classifications)[EXPLICIT_EXCLUSION], 17)
        self.assertEqual(summary.unexplained, (("2", "start"),))

    def test_added_removed_and_field_totals_reconcile(self):
        summary = self.classify(
            before={"1": row(), "removed": row()},
            native={"1": row(), "added": row()},
            base={"1": row()},
            control={"1": row()},
            recalculated={"1": row()},
        )
        self.assertEqual((summary.added_rows, summary.removed_rows), (1, 1))
        self.assertEqual(summary.unexplained_count, 2)
        summary.assert_reconciled()

    def test_duplicate_missing_and_wrong_shapes_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            unique_rows((("1", row()), ("1", row())))
        with self.assertRaisesRegex(ValueError, "no source identity"):
            unique_rows((("", row()),))
        with self.assertRaisesRegex(ValueError, "field contract"):
            self.classify(before={"1": ("short",)})

    def test_changed_engine_disposition_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "engine disposition changed"):
            self.classify(recalculated={})
        with self.assertRaisesRegex(ValueError, "common source identity"):
            self.classify(
                base={"1": row(), "not-observed": row()},
                control={"1": row(), "not-observed": row()},
                recalculated={"1": row(), "not-observed": row()},
            )

    def test_missing_engine_row_is_not_inferred_to_be_an_exclusion(self):
        with self.assertRaisesRegex(ValueError, "scheduled/excluded partition"):
            self.classify(
                before={"1": row(), "2": row()},
                native={"1": row(), "2": row()},
                base={"1": row()},
                control={"1": row()},
                recalculated={"1": row()},
            )
        with self.assertRaisesRegex(ValueError, "no code"):
            self.classify(
                before={"1": row(), "2": row()},
                native={"1": row(), "2": row()},
                base={"1": row()},
                control={"1": row()},
                recalculated={"1": row()},
                exclusions={"2": ""},
            )

    def test_exact_progress_edit_and_derived_duration_are_recognized(self):
        reasons = dict(
            classify_selected_progress(
                before_actual_start=None,
                after_actual_start="2026-09-08T07:30:00",
                expected_actual_start="2026-09-08T07:30:00",
                before_remaining=7200,
                after_remaining=3600,
                expected_remaining=3600,
                before_planned=7200,
                after_planned=3600,
                before_actual=0,
                after_actual=0,
                after_percent_permille=0,
                after_actual_finish=None,
                assignment_units_permille=2000,
                before_task_work=14400,
                after_task_work=7200,
                before_assignment_work=14400,
                after_assignment_work=7200,
                before_assignment_actual_work=0,
                after_assignment_actual_work=0,
                after_assignment_remaining_work=7200,
            )
        )
        self.assertEqual(reasons[DIRECT_CONTROLLED_EDIT], 2)
        self.assertEqual(reasons[PROJECT_DERIVED_PROGRESS_INPUT], 3)
        self.assertNotIn(UNEXPLAINED, reasons)

    def test_unjustified_native_derived_progress_is_unexplained(self):
        reasons = dict(
            classify_selected_progress(
                before_actual_start=None,
                after_actual_start="right",
                expected_actual_start="right",
                before_remaining=2,
                after_remaining=1,
                expected_remaining=1,
                before_planned=2,
                after_planned=9,
                before_actual=0,
                after_actual=0,
                after_percent_permille=0,
                after_actual_finish=None,
                assignment_units_permille=2000,
                before_task_work=4,
                after_task_work=2,
                before_assignment_work=4,
                after_assignment_work=2,
                before_assignment_actual_work=0,
                after_assignment_actual_work=0,
                after_assignment_remaining_work=2,
            )
        )
        self.assertEqual(reasons[UNEXPLAINED], 1)

    def test_unrequested_actual_duration_or_work_is_unexplained(self):
        common = dict(
            before_actual_start=None,
            after_actual_start="right",
            expected_actual_start="right",
            before_remaining=2,
            after_remaining=1,
            expected_remaining=1,
            before_planned=2,
            after_planned=9,
            before_actual=0,
            after_actual=0,
            after_percent_permille=0,
            after_actual_finish=None,
            assignment_units_permille=2000,
            before_task_work=4,
            after_task_work=2,
            before_assignment_work=4,
            after_assignment_work=2,
            before_assignment_actual_work=0,
            after_assignment_actual_work=0,
            after_assignment_remaining_work=2,
        )
        with_actual_duration = dict(common, after_actual=8)
        with_actual_work = dict(
            common,
            after_assignment_actual_work=1,
            after_assignment_remaining_work=1,
        )
        self.assertGreaterEqual(
            dict(classify_selected_progress(**with_actual_duration))[UNEXPLAINED],
            1,
        )
        self.assertGreaterEqual(
            dict(classify_selected_progress(**with_actual_work))[UNEXPLAINED],
            1,
        )


class ControlledNativeProgressEvidenceRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_record_uses_the_guarded_file_identities(self):
        for section, role in (
            ("baseline", "boiler_before"),
            ("native_output", "controlled_native"),
        ):
            digest, size = RECORDED[role]
            self.assertEqual(self.record[section]["sha256"], digest)
            self.assertEqual(self.record[section]["byte_size"], size)
        digest, size = RECORDED["controlled_native_repeat"]
        repeat = self.record["repeat_result"]["native_output"]
        self.assertEqual(repeat["sha256"], digest)
        self.assertEqual(repeat["byte_size"], size)

    def test_record_preserves_the_first_result_and_keeps_static_mismatches_open(self):
        cohort = self.record["cohort"]
        self.assertEqual(
            sum(cohort["classifications"].values()), cohort["field_slots"]
        )
        self.assertEqual(cohort["classifications"][UNEXPLAINED], 3)
        self.assertEqual(len(cohort["unexplained"]), 3)
        repeat = self.record["repeat_result"]["cohort"]
        self.assertEqual(
            sum(repeat["classifications"].values()), repeat["field_slots"]
        )
        self.assertEqual(repeat["classifications"][UNEXPLAINED], 0)
        self.assertEqual(repeat["unexplained"], [])
        self.assertGreater(repeat["classifications"][BASELINE_MISMATCH], 0)
        self.assertEqual(
            repeat["baseline_mismatches"]["count"],
            repeat["classifications"][BASELINE_MISMATCH],
        )
        self.assertEqual(self.record["gate"]["met"], 4)
        self.assertFalse(self.record["gate"]["P1-G2"])
        self.assertTrue(self.record["gate"]["P1-G3"])

    def test_record_pins_the_clean_repeat_without_customer_names(self):
        repeat = self.record["next_experiment"]
        self.assertEqual(repeat["source_uid"], "227")
        self.assertEqual(repeat["sto_changed_supported_baseline_exact_rows"], 12)
        self.assertEqual(repeat["sto_downstream_moved_rows"], 6)
        self.assertNotIn("task_name", EVIDENCE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
