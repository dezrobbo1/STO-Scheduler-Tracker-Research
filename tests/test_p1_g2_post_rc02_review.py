"""Tests for the post-RC02 P1-G2 root-cause review."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.evidence import p1_g2_post_rc02_review as review

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/p1-g2-post-rc02-review-2026-09-25.json"
SCRIPT = ROOT / "scripts/evidence/p1_g2_post_rc02_review.py"


class PostRc02ReviewTests(unittest.TestCase):
    def test_committed_record_replays_exactly(self):
        expected = review.serialize(review.build_record())
        self.assertEqual(EVIDENCE.read_text(encoding="utf-8"), expected)
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--check", str(EVIDENCE)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_current_inventory_and_rc01_roots_are_revalidated(self):
        record = review.build_record()
        self.assertEqual(record["current_inventory"]["slots"], 147)
        self.assertEqual(record["current_inventory"]["leaves"], 39)
        self.assertEqual(
            record["current_inventory"]["by_group"],
            {"G2-RC01": 143, "G2-RC03": 3, "G2-RC04": 1},
        )
        self.assertEqual(record["current_inventory"]["rc02_slots"], 0)
        rc01 = record["rc01_review"]
        self.assertEqual(rc01["classification"], "REVALIDATED_STRONG_CANDIDATE")
        self.assertEqual(rc01["current_slots"], 143)
        self.assertEqual(rc01["current_leaves"], 37)
        self.assertEqual(rc01["root_leaf_count"], 10)
        self.assertTrue(rc01["root_shape"]["all_roots_match"])
        self.assertEqual(rc01["root_shape"]["assignment_count"], 2)
        self.assertEqual(rc01["root_shape"]["resource_calendar_count"], 2)
        self.assertEqual(rc01["replacement_semantics_status"], "NOT_ESTABLISHED")
        self.assertFalse(rc01["production_correction_authorized"])

    def test_rc03_stays_proven_but_has_no_replacement_semantic_yet(self):
        record = review.build_record()
        rc03 = record["rc03_review"]
        self.assertEqual(rc03["classification"], "PROVEN_ORIGIN_REMAINS")
        self.assertEqual(rc03["current_slots"], 3)
        self.assertEqual(rc03["current_leaves"], 2)
        self.assertEqual(rc03["causal_confidence"], "PROVEN")
        self.assertEqual(rc03["replacement_semantics_status"], "NOT_ESTABLISHED")
        self.assertFalse(rc03["production_correction_authorized"])

    def test_rc04_old_compound_parentage_is_not_reused_as_current_cause(self):
        record = review.build_record()
        rc04 = record["rc04_review"]
        self.assertEqual(
            rc04["classification"],
            "HISTORICAL_COMPOUND_LABEL_REQUIRES_RECLASSIFICATION",
        )
        self.assertEqual(rc04["historical_parent_groups"], ["G2-RC01", "G2-RC02"])
        self.assertEqual(rc04["current_rc02_slots"], 0)
        self.assertFalse(rc04["independent_fix_authorized"])

    def test_next_experiment_is_native_first_and_does_not_authorize_a_fix(self):
        experiment = review.build_record()["next_experiment"]
        self.assertEqual(
            experiment["id"],
            "P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1",
        )
        self.assertEqual(experiment["status"], "PREDECLARED_NOT_RUN")
        self.assertTrue(experiment["native_return_required"])
        self.assertFalse(experiment["boiler_counterfactual_authorized"])
        self.assertFalse(experiment["production_correction_authorized"])
        self.assertEqual({case["id"] for case in experiment["cases"]}, {"A", "B", "C", "D"})

    def test_missing_current_rc01_root_fails_closed(self):
        historical, post = review.load_inputs()
        mutated = deepcopy(post)
        mutated["inventory"]["remaining_mismatches"] = [
            row
            for row in mutated["inventory"]["remaining_mismatches"]
            if row["leaf_id"] != review.RC01_ROOTS[0]
        ]
        with self.assertRaises(review.EvidenceError):
            review.review_documents(historical, mutated)

    def test_historical_rc01_shape_drift_fails_closed(self):
        historical, post = review.load_inputs()
        mutated = deepcopy(historical)
        mutated["activities"][review.RC01_ROOTS[0]]["assignment_count"] = 1
        with self.assertRaisesRegex(review.EvidenceError, "root shape drifted"):
            review.review_documents(mutated, post)

    def test_rc02_residual_fails_closed(self):
        historical, post = review.load_inputs()
        mutated = deepcopy(post)
        row = deepcopy(mutated["inventory"]["remaining_mismatches"][0])
        row["diagnostic_group"] = "G2-RC02"
        mutated["inventory"]["remaining_mismatches"][0] = row
        with self.assertRaises(review.EvidenceError):
            review.review_documents(historical, mutated)


if __name__ == "__main__":
    unittest.main()
