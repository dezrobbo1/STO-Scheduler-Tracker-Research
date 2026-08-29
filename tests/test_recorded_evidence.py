from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT
    / "results"
    / "phase1"
    / "boiler-mspdi-import-and-calculation-evidence-v0.2.json"
)


class RecordedBoilerV02EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.serialized = EVIDENCE.read_text(encoding="utf-8")
        cls.evidence = json.loads(cls.serialized)

    def test_identity_claim_boundary_and_reproducibility_are_explicit(self) -> None:
        self.assertEqual(
            self.evidence["source"]["source_sha256"],
            "e6a3739976580e2144352011f818c0099c0dc0c278fb37a976c5b6a55fbc3420",
        )
        self.assertEqual(
            self.evidence["source"]["canonical_sha256"],
            "e1af182f32a5c090e533a5694c885d0387633bba61c2f24d9b5aaf22511a0dc6",
        )
        self.assertEqual(self.evidence["native_project_validation"], "not_executed")
        self.assertFalse(self.evidence["source_xml_committed"])
        self.assertFalse(self.evidence["full_canonical_output_committed"])
        for key, value in self.evidence["reproducibility"].items():
            if key.endswith("_equal"):
                self.assertIs(value, True, key)

    def test_record_contains_no_raw_id_arrays_or_difference_records(self) -> None:
        self.assertNotIn('"activity_id"', self.serialized)
        self.assertNotIn('"relationship_id"', self.serialized)
        self.assertNotIn('"differences"', self.serialized)
        self.assertNotIn("task:", self.serialized)
        self.assertNotIn("relationship:", self.serialized)

        def assert_no_lists(value: object) -> None:
            self.assertNotIsInstance(value, list)
            if isinstance(value, dict):
                for child in value.values():
                    assert_no_lists(child)

        assert_no_lists(self.evidence)

    def test_baseline_delta_and_changed_cohort_are_consistent(self) -> None:
        comparison = self.evidence["baseline_comparison"]
        counts = comparison["profile_counts"]
        for key, delta in counts["delta"].items():
            self.assertEqual(counts["v0_2"][key] - counts["v0_1"][key], delta)

        changed = comparison["changed_cohorts"]
        self.assertEqual(changed["newly_eligible_activities"], 56)
        self.assertEqual(
            changed["direct_negative_elapsed_fs_lead_successors"]
            + changed["downstream_dependency_closure_activities"],
            changed["newly_eligible_activities"],
        )
        self.assertEqual(
            comparison["changed_cohort_comparison"],
            {
                "compared_activities": 56,
                "coordinate_differences": 0,
                "difference_activity_ids_sha256": (
                    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
                ),
                "exact_coordinate_matches": 56,
            },
        )


if __name__ == "__main__":
    unittest.main()
