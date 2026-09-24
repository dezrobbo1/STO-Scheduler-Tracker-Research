"""Tests for the bounded RC02 latest-successor BOILER counterfactual."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.evidence import p1_g2_rc02_latest_successor_boiler_counterfactual as latest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/evidence/p1_g2_rc02_latest_successor_boiler_counterfactual.py"
RESULT = ROOT / "docs/evidence/p1-g2-rc02-latest-successor-boiler-counterfactual-2026-09-25.json"


class LatestSuccessorBoilerCounterfactualTests(unittest.TestCase):
    def test_predeclared_basis_is_pinned(self):
        self.assertEqual(latest.MAIN_BASIS, "d6ce148e6d3ff489d5173a99ebd2f0c4176de636")
        self.assertEqual(
            latest.prior_cf.production_source_digest(),
            latest.PRODUCTION_SOURCE_DIGEST,
        )
        self.assertEqual(
            latest.EXPECTED_SELECTED,
            frozenset(
                {
                    ("L0055", "L0052", "L0060"),
                    ("L0400", "L0388", "L0389"),
                }
            ),
        )
        self.assertEqual(
            latest.EXPECTED_DROPPED_BACKWARD,
            frozenset({("L0055", "L0052", "L0056")}),
        )

    def test_native_latest_successor_basis_is_exact_and_bounded(self):
        record = latest.read_native_result()
        self.assertEqual(record["project"]["build_number"], latest.NATIVE_BUILD)
        self.assertEqual(
            record["classification"]["components"],
            {
                "forward_semantic": "ZERO_DURATION_FANOUT_FORWARD_PASSTHROUGH_SUPPORTED",
                "backward_semantic": "LATEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED",
                "free_slack_observation": "SENTINEL_CHANGED_MATCHES_INACTIVE_EDGE_GAP",
            },
        )
        # The earlier experiment did not authorize the BOILER rerun. This file
        # exists precisely to make the latest-successor hypothesis a new,
        # separately predeclared diagnostic rather than rewriting that verdict.
        self.assertFalse(
            record["classification"]["decision"]["boiler_counterfactual_rerun_authorized"]
        )
        self.assertFalse(
            record["classification"]["decision"]["production_scheduler_change_authorized"]
        )

    def test_prior_symmetric_counterfactual_is_pinned(self):
        record = latest.read_prior_counterfactual()
        self.assertEqual(record["inventory"]["before"]["slots"], 422)
        self.assertEqual(record["inventory"]["after"]["slots"], 166)
        self.assertEqual(record["rc02"]["slots_before"], 258)
        self.assertEqual(record["rc02"]["slots_after"], 19)
        self.assertEqual(len(latest._expected_prior_rc02_keys(record)), 19)
        self.assertFalse(record["acceptance"]["counterfactual_success"])

    def test_same_count_different_rc02_residue_fails_closed(self):
        prior = latest.read_prior_counterfactual()
        expected = set(latest._expected_prior_rc02_keys(prior))
        wrong = set(expected)
        wrong.remove(sorted(wrong)[0])
        wrong.add(("L0056", "early_start"))
        self.assertEqual(len(wrong), len(expected))
        with self.assertRaisesRegex(
            latest.LatestSuccessorCounterfactualError,
            "exact prior 19-slot residue",
        ):
            latest._require_exact_prior_rc02_residue(wrong, prior)

    def test_reopened_non_rc02_symmetric_slot_fails_closed(self):
        prior = latest.read_prior_counterfactual()
        expected_rc02 = latest._expected_prior_rc02_keys(prior)
        retained_non_rc02 = ("L9998", "late_start")
        reopened_non_rc02 = ("L9999", "late_start")
        symmetric = set(expected_rc02) | {retained_non_rc02}
        directional = {retained_non_rc02, reopened_non_rc02}
        with self.assertRaisesRegex(
            latest.LatestSuccessorCounterfactualError,
            "outside the exact prior RC02 residue",
        ):
            latest._require_exact_symmetric_to_directional_transition(
                symmetric, directional, expected_rc02
            )

    def test_committed_result_is_exact_bounded_success(self):
        record = json.loads(RESULT.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], latest.SCHEMA)
        self.assertEqual(record["basis"]["fresh_main"], latest.MAIN_BASIS)
        self.assertEqual(
            record["basis"]["evidence_tool"]["sha256"],
            hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        )
        self.assertEqual(record["inventory"]["production"]["slots"], 422)
        self.assertEqual(record["inventory"]["symmetric_direct_splice"]["slots"], 166)
        self.assertEqual(record["inventory"]["latest_successor_directional"]["slots"], 147)
        self.assertEqual(record["inventory"]["new_slots"], 0)
        self.assertEqual(record["rc02"]["slots_before"], 258)
        self.assertEqual(record["rc02"]["slots_after_symmetric"], 19)
        self.assertEqual(record["rc02"]["slots_after_latest_successor"], 0)
        self.assertTrue(record["rc02"]["exact_prior_19_slot_residue_closed"])
        self.assertEqual(
            record["movement_by_original_group"]["G2-RC02"],
            {"closed": 258},
        )
        self.assertEqual(
            record["movement_by_original_group"]["G2-RC01"],
            {"closed": 17, "improved": 11, "unchanged": 132},
        )
        self.assertTrue(record["acceptance"]["counterfactual_success"])
        self.assertTrue(record["acceptance"]["prior_166_slot_symmetric_stage_reproduced"])
        self.assertTrue(record["acceptance"]["prior_19_slot_rc02_residue_reproduced"])
        self.assertTrue(record["acceptance"]["exact_symmetric_stage_transition"])
        self.assertTrue(record["acceptance"]["all_rc02_slots_closed"])
        self.assertTrue(record["acceptance"]["no_other_family_worsened"])
        self.assertEqual(
            record["decision"]["classification"],
            "RC02_LATEST_SUCCESSOR_COUNTERFACTUAL_SUPPORTED",
        )
        self.assertTrue(
            record["decision"]["separate_bounded_production_rc02_correction_pr_authorized"]
        )
        self.assertFalse(record["decision"]["production_scheduler_changed"])
        self.assertFalse(record["decision"]["p1_g2_closed"])
        self.assertEqual(record["decision"]["p1_gate"], "4/5 IN PROGRESS")
        self.assertFalse(record["decision"]["p2_started"])

    def test_committed_selection_is_unique_latest_successor(self):
        record = json.loads(RESULT.read_text(encoding="utf-8"))
        selection = {
            (row["active_predecessor_leaf_id"], row["inactive_leaf_id"]): row
            for row in record["transform"]["latest_successor_selection"]
        }
        self.assertEqual(
            selection[("L0055", "L0052")]["selected_latest_successor_leaf_id"],
            "L0060",
        )
        self.assertEqual(
            selection[("L0400", "L0388")]["selected_latest_successor_leaf_id"],
            "L0389",
        )
        for row in selection.values():
            calculated = [candidate["calculated_late_start"] for candidate in row["candidates"]]
            source = [candidate["source_late_start"] for candidate in row["candidates"]]
            self.assertEqual(calculated, source)
        self.assertEqual(
            record["transform"]["dropped_backward_splices"],
            [{
                "predecessor_leaf_id": "L0055",
                "inactive_leaf_id": "L0052",
                "successor_leaf_id": "L0056",
            }],
        )
        self.assertTrue(record["transform"]["unfiltered_wrapper_matches_production_backward"])

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
            self.assertIn("fixture identity mismatch", result.stderr)

    def test_cli_refuses_output_aliases_before_reading_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xml"
            source.write_text("immutable", encoding="utf-8")
            before = source.read_bytes()
            symlink = root / "alias.xml"
            symlink.symlink_to(source)
            hardlink = root / "hard.xml"
            os.link(source, hardlink)
            for output in (source, symlink, hardlink):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(source), "--output", str(output)],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("output/check path must be separate", result.stderr)
                self.assertEqual(source.read_bytes(), before)

    def test_external_baseline_reproduces_committed_result_when_present(self):
        value = os.environ.get("STO_RC02_BOILER_BASELINE")
        if not value:
            if os.environ.get("STO_REQUIRE_RC02_LATEST_SUCCESSOR_COUNTERFACTUAL") == "1":
                self.fail("STO_RC02_BOILER_BASELINE is required")
            self.skipTest("external BOILER baseline not supplied")
        source = Path(value)
        before = source.read_bytes()
        record = latest.build_record(source)
        if not RESULT.exists():
            self.skipTest("committed result is intentionally absent before execution")
        self.assertEqual(latest.serialize(record).encode("utf-8"), RESULT.read_bytes())
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(source), "--check", str(RESULT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
