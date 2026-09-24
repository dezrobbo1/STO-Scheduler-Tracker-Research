"""Tests for the post-correction P1-G2 RC02 production evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.evidence import p1_g2_rc02_production_verification as verification

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "docs/evidence/p1-g2-rc02-production-correction-2026-09-25.json"
SCRIPT = ROOT / "scripts/evidence/p1_g2_rc02_production_verification.py"


class Rc02ProductionVerificationTests(unittest.TestCase):
    def test_worker_and_production_basis_are_the_correction_commit(self):
        self.assertEqual(verification.REPOSITORY_BASE, verification.PRODUCTION_COMMIT)
        self.assertEqual(
            verification.PRODUCTION_BASIS_PATH_TREE_SHA256,
            verification.EXPECTED_PATH_TREE_SHA256,
        )
        self.assertEqual(
            verification.prior_cf.production_source_digest(),
            verification.PRODUCTION_SOURCE_DIGEST,
        )

    def test_committed_result_is_exact_counterfactual_equivalence(self):
        record = json.loads(RESULT.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], verification.SCHEMA)
        self.assertEqual(record["inventory"]["before_slots"], 422)
        self.assertEqual(record["inventory"]["after_slots"], 147)
        self.assertEqual(record["inventory"]["after_leaves"], 39)
        self.assertEqual(record["inventory"]["rc02_slots_after"], 0)
        self.assertEqual(
            record["inventory"]["by_group"],
            {"G2-RC01": 143, "G2-RC03": 3, "G2-RC04": 1},
        )
        self.assertEqual(record["production_semantics"]["backward_profile"], "sto-backward-pass-v8")
        self.assertEqual(record["production_semantics"]["criticality_profile"], "sto-criticality-v7")
        self.assertEqual(record["production_semantics"]["validator_profile"], "sto-validator-v4")
        self.assertTrue(record["verification"]["projection_matches_supported_counterfactual"])
        self.assertTrue(record["verification"]["remaining_keyset_matches_supported_counterfactual"])
        self.assertEqual(
            record["verification"]["projection_sha256"],
            verification.EXPECTED_PROJECTION_SHA256,
        )
        self.assertEqual(
            record["verification"]["remaining_keyset_sha256"],
            verification.EXPECTED_REMAINING_KEYSET_SHA256,
        )
        self.assertEqual(
            record["decision"]["classification"],
            "RC02_PRODUCTION_CORRECTION_VERIFIED",
        )
        self.assertTrue(record["decision"]["rc02_closed_in_production"])
        self.assertFalse(record["decision"]["p1_g2_closed"])
        self.assertEqual(record["decision"]["p1_gate"], "4/5 IN PROGRESS")
        self.assertFalse(record["decision"]["p2_started"])

    def test_remaining_rows_are_sanitized_unique_and_reconcile(self):
        record = json.loads(RESULT.read_text(encoding="utf-8"))
        rows = record["inventory"]["remaining_mismatches"]
        keys = {(row["leaf_id"], row["field"]) for row in rows}
        self.assertEqual(len(rows), 147)
        self.assertEqual(len(keys), 147)
        self.assertFalse(any("name" in row or "source_uid" in row for row in rows))
        self.assertFalse(any(row["diagnostic_group"] == "G2-RC02" for row in rows))

    def test_external_baseline_reproduces_exact_result_when_present(self):
        value = os.environ.get("STO_RC02_PRODUCTION_BASELINE")
        if not value:
            if os.environ.get("STO_REQUIRE_RC02_PRODUCTION") == "1":
                self.fail("STO_RC02_PRODUCTION_BASELINE is required")
            self.skipTest("external BOILER baseline not supplied")
        source = Path(value)
        before = source.read_bytes()
        record = verification.build_record(source)
        self.assertEqual(verification.serialize(record).encode("utf-8"), RESULT.read_bytes())
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(source), "--check", str(RESULT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
