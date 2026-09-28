"""Bounded RC01 production evidence, with a required-mode real fixture gate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.evidence import p1_g2_rc01_production_verification as verification
from scripts.evidence import p1_g2_post_rc02_review as safe


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "docs/evidence/p1-g2-rc01-production-correction-2026-09-28.json"


class Rc01ProductionEvidenceTests(unittest.TestCase):
    def test_committed_movement_and_historical_evidence(self):
        record = json.loads(RESULT.read_bytes())
        self.assertEqual(record["schema"], verification.SCHEMA)
        self.assertEqual(record["starting_main"], verification.BASE_MAIN)
        self.assertEqual(record["before"], {"slots": 147, "leaves": 39,
                                           "by_group": {"G2-RC01": 144, "G2-RC03": 3}})
        self.assertEqual(record["after"]["remaining_keys"],
                         [list(key) for key in sorted(verification.SURVIVING)])
        self.assertEqual(record["after"]["slots"], 3)
        self.assertEqual(record["movement"]["closed_rc01"], 144)
        self.assertEqual(record["movement"]["closed_first_divergences"], 22)
        self.assertEqual(set(record["movement"]["root_movement"]), verification.ROOTS)
        self.assertEqual(record["movement"]["new_keys"], [])
        self.assertEqual(record["movement"]["worsened_keys"], [])
        self.assertEqual(record["validator"]["violations"], [])
        self.assertFalse(record["historical_evidence"]["historical_production_authorization"])
        self.assertEqual(record["historical_evidence"]["r6_verdict"],
                         "V3_NETWORKED_ASSIGNMENT_ENVELOPE_INCONCLUSIVE")
        self.assertEqual(record["historical_evidence"]["post_rc02_sha256"],
                         hashlib.sha256(verification.HISTORICAL.read_bytes()).hexdigest())
        self.assertEqual(record["historical_evidence"]["counterfactual_sha256"],
                         hashlib.sha256(verification.COUNTERFACTUAL.read_bytes()).hexdigest())
        self.assertEqual(record["historical_evidence"]["r6_inconclusive_sha256"],
                         hashlib.sha256(verification.R6.read_bytes()).hexdigest())

    def test_output_refuses_aliased_sources_without_touching_them(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            baseline = folder / "baseline.xml"
            baseline.write_bytes(b"source unchanged")
            source_bytes = baseline.read_bytes()
            symlink = folder / "symlink.xml"
            symlink.symlink_to(baseline)
            hardlink = folder / "hardlink.xml"
            os.link(baseline, hardlink)
            aliases = (baseline, folder / "other" / ".." / "baseline.xml",
                       symlink, hardlink)
            (folder / "other").mkdir()
            for alias in aliases:
                with self.subTest(alias=alias):
                    with self.assertRaisesRegex(safe.EvidenceError, "aliases"):
                        safe.refuse_output_alias(alias, verification.protected(baseline))
                    self.assertEqual(baseline.read_bytes(), source_bytes)

    def test_atomic_replacement_of_separate_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            baseline = folder / "baseline.xml"
            baseline.write_bytes(b"source unchanged")
            candidate = folder / "candidate.json"
            candidate.write_bytes(b"prior candidate")
            actual_replace = os.replace
            observed = []
            def replace(temporary, destination):
                observed.append((Path(temporary).read_bytes(), candidate.read_bytes()))
                actual_replace(temporary, destination)
            with mock.patch.object(safe.os, "replace", side_effect=replace):
                safe.write_output_safely(candidate, "new result\n",
                                         verification.protected(baseline))
            self.assertEqual(observed, [(b"new result\n", b"prior candidate")])
            self.assertEqual(candidate.read_bytes(), b"new result\n")
            self.assertEqual(baseline.read_bytes(), b"source unchanged")

    def test_invalid_baseline_identity_is_rejected_before_calculation(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "wrong.xml"
            wrong.write_bytes(b"not the controlled BOILER baseline")
            with self.assertRaisesRegex(verification.VerificationError, "identity differs"):
                verification.build_record(wrong)
            self.assertEqual(wrong.read_bytes(), b"not the controlled BOILER baseline")

    def test_exact_boiler_production_acceptance_required_mode(self):
        path = os.environ.get("STO_RC01_PRODUCTION_BOILER")
        if not path:
            if os.environ.get("STO_REQUIRE_RC01_PRODUCTION") == "1":
                self.fail("STO_RC01_PRODUCTION_BOILER must supply exact real BOILER fixture")
            self.skipTest("external BOILER baseline not supplied")
        source = Path(path)
        before = source.read_bytes()
        result = verification.build_record(source)
        self.assertEqual(verification.serialize(result).encode(), RESULT.read_bytes())
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
