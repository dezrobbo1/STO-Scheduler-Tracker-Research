"""Regression tests for the one-field RC02 Free-Slack sentinel evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts.evidence import p1_g2_free_slack_sentinel as sentinel
from scripts.evidence import p1_g2_inactive_native_matrix_generate as generate

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/p1-g2-rc02-free-slack-sentinel-result-2026-09-24.json"
SCRIPT = ROOT / "scripts/evidence/p1_g2_free_slack_sentinel.py"
GENERATOR = ROOT / "scripts/evidence/p1_g2_inactive_native_matrix_generate.py"


class Rc02FreeSlackSentinelTests(unittest.TestCase):
    def test_sentinel_generator_is_exact_one_field_mutation(self):
        baseline = generate.build_fixture()
        candidate = generate.build_free_slack_sentinel_fixture()
        self.assertEqual(len(candidate), 48326)
        self.assertEqual(hashlib.sha256(candidate).hexdigest(), sentinel.SENTINEL_SHA256)

        left = [(e.tag, e.text, e.attrib, e.tail) for e in ET.fromstring(baseline).iter()]
        right = [(e.tag, e.text, e.attrib, e.tail) for e in ET.fromstring(candidate).iter()]
        differences = [(a, b) for a, b in zip(left, right) if a != b]
        self.assertEqual(len(differences), 1)
        self.assertTrue(differences[0][0][0].endswith("FreeSlack"))
        self.assertEqual((differences[0][0][1], differences[0][1][1]), ("0", "12345"))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sentinel.xml"
            result = subprocess.run(
                [sys.executable, str(GENERATOR), str(output), "--free-slack-sentinel"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), candidate)

    def test_committed_record_replays_validation(self):
        record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], sentinel.SCHEMA)
        self.assertEqual(record["validation"], sentinel.replay(record))
        self.assertTrue(record["validation"]["active_controls"]["valid"])
        self.assertEqual(
            record["validation"]["date_semantic"],
            "ZERO_DURATION_FS_PASSTHROUGH_SUPPORTED",
        )
        self.assertEqual(record["validation"]["pair_c"]["returned_free_slack"], 0)
        self.assertTrue(record["conclusion"]["unchanged_sentinel_retention_ruled_out"])
        self.assertTrue(record["conclusion"]["diagnostic_boiler_counterfactual_authorized"])
        self.assertFalse(record["conclusion"]["production_scheduler_change_authorized"])
        self.assertFalse(record["input_lineage"]["machine_proven_from_return_alone"])

    def test_verifier_requires_owner_lineage_confirmation(self):
        path = os.environ.get("STO_RC02_SENTINEL_RETURN")
        if not path:
            self.skipTest("external sentinel return not supplied")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), path],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("owner confirmation", result.stderr)

    def test_external_return_reproduces_exact_committed_record(self):
        path = os.environ.get("STO_RC02_SENTINEL_RETURN")
        if not path:
            if os.environ.get("STO_REQUIRE_RC02_SENTINEL") == "1":
                self.fail("STO_RC02_SENTINEL_RETURN is required")
            self.skipTest("external sentinel return not supplied")

        before = Path(path).read_bytes()
        record = sentinel.analyze(before, owner_confirmed_opened_sentinel=True)
        self.assertEqual(sentinel.serialize(record).encode("utf-8"), EVIDENCE.read_bytes())
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                path,
                "--confirm-opened-sentinel",
                "--check",
                str(EVIDENCE),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(path).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
