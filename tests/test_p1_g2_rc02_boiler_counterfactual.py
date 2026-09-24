"""Tests for the bounded P1-G2 RC02 BOILER counterfactual evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.evidence import p1_g2_rc02_boiler_counterfactual as counterfactual

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/p1-g2-rc02-boiler-counterfactual-2026-09-24.json"
SCRIPT = ROOT / "scripts/evidence/p1_g2_rc02_boiler_counterfactual.py"


class Rc02BoilerCounterfactualTests(unittest.TestCase):
    def test_historical_production_source_basis_is_pinned(self):
        record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(
            record["basis"]["production_source_digest"],
            counterfactual.PRODUCTION_SOURCE_DIGEST,
        )
        self.assertEqual(
            counterfactual.MAIN_BASIS,
            "43333a871916368359eb705e9080a9522e12db2b",
        )

    def test_fixed_inventory_identity_and_contract(self):
        record = counterfactual.read_inventory()
        self.assertEqual(record["schema"], "sto-p1-g2-baseline-root-causes-v3")
        self.assertEqual(len(record["mismatches"]), 422)
        self.assertEqual(
            {(row["leaf_id"], row["field"]) for row in record["mismatches"]}
            .__len__(),
            422,
        )

    def test_committed_result_records_partial_not_false_success(self):
        record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], counterfactual.SCHEMA)
        self.assertEqual(record["inventory"]["before"]["slots"], 422)
        self.assertEqual(record["inventory"]["after"]["slots"], 166)
        self.assertEqual(record["inventory"]["closed_slots"], 256)
        self.assertEqual(record["inventory"]["new_slots"], 0)
        self.assertEqual(record["rc02"]["slots_before"], 258)
        self.assertEqual(record["rc02"]["slots_after"], 19)
        self.assertEqual(record["rc02"]["closed_slots"], 239)
        self.assertEqual(record["rc02"]["leaves_after"], 9)
        self.assertEqual(
            record["movement_by_original_group"]["G2-RC02"],
            {"closed": 239, "improved": 15, "worsened": 4},
        )
        self.assertEqual(
            record["movement_by_original_group"]["G2-RC01"],
            {"closed": 17, "improved": 11, "unchanged": 132},
        )
        self.assertEqual(
            record["movement_by_original_group"]["G2-RC03"],
            {"unchanged": 3},
        )
        self.assertEqual(
            record["movement_by_original_group"]["G2-RC04"],
            {"improved": 1},
        )
        self.assertFalse(record["acceptance"]["counterfactual_success"])
        self.assertFalse(record["acceptance"]["all_rc02_first_divergence_roots_closed"])
        self.assertFalse(record["acceptance"]["all_rc02_paths_non_worsening"])
        self.assertTrue(record["acceptance"]["no_new_mismatch_slots"])
        self.assertTrue(record["acceptance"]["no_other_family_worsened"])
        self.assertFalse(record["decision"]["production_correction_authorized"])
        self.assertFalse(record["decision"]["p1_g2_closed"])
        self.assertEqual(record["decision"]["p1_gate"], "4/5 IN PROGRESS")
        self.assertFalse(record["decision"]["p2_started"])

    def test_transform_is_exact_bounded_splice_set(self):
        record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        actual = {
            (
                row["active_predecessor_leaf_id"],
                row["inactive_leaf_id"],
                row["active_successor_leaf_id"],
            )
            for row in record["transform"]["splices"]
        }
        self.assertEqual(actual, counterfactual.EXPECTED_SPLICES)
        self.assertEqual(record["transform"]["synthetic_relationship_count"], 3)
        free_slack = record["transform"]["free_slack_shape_check"]
        self.assertTrue(free_slack["all_equivalent"])
        self.assertEqual(
            free_slack["basis"],
            "hash-verified BOILER source observations before diagnostic transform",
        )
        boundaries = {
            row["active_predecessor_leaf_id"]: row
            for row in free_slack["boundaries"]
        }
        self.assertEqual(
            boundaries["L0055"]["source_direct_successor_gap_seconds_by_leaf"],
            {"L0056": 0, "L0060": 0},
        )
        self.assertEqual(
            boundaries["L0400"]["source_direct_successor_gap_seconds_by_leaf"],
            {"L0389": 0},
        )
        for row in boundaries.values():
            self.assertEqual(row["source_predecessor_free_slack_seconds"], 0)
            self.assertEqual(row["source_inactive_edge_gap_seconds"], 0)
            self.assertTrue(row["source_free_slack_matches_inactive_edge_gap"])
            self.assertTrue(
                row["all_source_direct_successor_gaps_match_inactive_edge_gap"]
            )
        self.assertFalse(record["scope"]["production_scheduler_changed"])
        self.assertFalse(record["scope"]["imported_schedule_changed"])

    def test_residue_is_localized_to_unmeasured_fanout(self):
        record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        residue = record["rc02"]["fanout_residue"]
        self.assertEqual(residue["remaining_rc02_path_roots"], ["L0055"])
        self.assertEqual(residue["remaining_rc02_leaf_count"], 9)
        self.assertEqual(
            residue["remaining_rc02_by_field"],
            {"late_finish": 9, "late_start": 9, "total_float": 1},
        )
        self.assertEqual(residue["fanout_boundary"]["active_successor_count"], 2)
        self.assertEqual(residue["single_successor_boundary"]["active_successor_count"], 1)
        roots = {row["leaf_id"]: row for row in record["rc02"]["root_outcomes"]}
        self.assertEqual(roots["L0055"]["status"], "PARTIAL")
        self.assertEqual(
            roots["L0055"]["remaining_first_divergence_fields"],
            ["late_finish", "late_start"],
        )
        self.assertEqual(
            {leaf for leaf, row in roots.items() if row["status"] == "CLOSED"},
            {"L0056", "L0060", "L0389", "L0400"},
        )

    def test_wrong_baseline_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.xml"
            path.write_text("<Project/>", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("production source basis changed", result.stderr)

    def test_external_baseline_reproduces_committed_record(self):
        value = os.environ.get("STO_RC02_BOILER_BASELINE")
        if not value:
            if os.environ.get("STO_REQUIRE_RC02_BOILER_COUNTERFACTUAL") == "1":
                self.fail("STO_RC02_BOILER_BASELINE is required")
            self.skipTest("external BOILER baseline not supplied")
        source = Path(value)
        before = source.read_bytes()
        record = counterfactual.build_record(source)
        self.assertEqual(
            counterfactual.serialize(record).encode("utf-8"),
            EVIDENCE.read_bytes(),
        )
        check = subprocess.run(
            [sys.executable, str(SCRIPT), str(source), "--check", str(EVIDENCE)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
