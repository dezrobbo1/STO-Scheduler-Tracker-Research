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
        self.assertFalse(record["acceptance"]["counterfactual_success"])

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
