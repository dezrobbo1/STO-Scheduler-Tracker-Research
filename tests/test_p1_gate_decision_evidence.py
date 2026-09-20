from __future__ import annotations

import json
from pathlib import Path
import unittest

from tests.native_transition_evidence import FIELD_NAMES
from tests.real_fixture_guard import RECORDED


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "docs/evidence/p1-gate-entry-decision-2026-09-20.json"


class P1GateDecisionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serialized = DECISION.read_text(encoding="utf-8")
        cls.record = json.loads(cls.serialized)

    def test_fixture_identities_match_the_existing_guard(self):
        fixtures = self.record["fixtures"]
        for recorded_name, guard_name in (
            ("boiler_untouched", "boiler_untouched"),
            ("boiler_before", "boiler_before"),
            ("boiler_after_native", "after_native"),
            ("boiler_task43_project_saved", "roundtrip_saved"),
        ):
            digest, size = RECORDED[guard_name]
            self.assertEqual(fixtures[recorded_name]["sha256"], digest)
            self.assertEqual(fixtures[recorded_name]["bytes"], size)
        day5_digest, day5_size = RECORDED["day5"]
        self.assertFalse(fixtures["boiler_day5"]["available"])
        self.assertEqual(fixtures["boiler_day5"]["sha256_recorded_prefix"], day5_digest)
        self.assertEqual(fixtures["boiler_day5"]["bytes_recorded"], day5_size)

    def test_native_transition_totals_and_field_contract_reconcile(self):
        transition = self.record["native_transition"]
        self.assertEqual(transition["field_contract"], list(FIELD_NAMES))
        self.assertEqual(
            transition["common_rows"],
            transition["unchanged_common_rows"] + transition["changed_common_rows"],
        )
        self.assertEqual(
            transition["changed_common_rows"],
            transition["documented_completion_rows"]
            + transition["unexplained_changed_common_rows"],
        )
        self.assertEqual(
            transition["unresolved_identity_rows"],
            transition["before_only_rows"] + transition["after_only_rows"],
        )
        self.assertEqual(
            transition["unresolved_rows"],
            transition["unexplained_changed_common_rows"]
            + transition["unresolved_identity_rows"],
        )

    def test_open_gate_is_not_relabelled_as_passed(self):
        gate = self.record["gate"]
        self.assertTrue(gate["P1-G2"].startswith("open_"))
        self.assertTrue(gate["P1-G3"].startswith("open_"))
        self.assertEqual(
            gate["decision"], "limited_development_exception_proposed_not_enacted"
        )
        self.assertNotIn('"task_name"', self.serialized)


if __name__ == "__main__":
    unittest.main()
