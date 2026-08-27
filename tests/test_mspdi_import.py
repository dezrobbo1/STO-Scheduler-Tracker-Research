from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sto_scheduler_core import canonical_sha256, import_mspdi, inventory_mspdi, validate_canonical_schedule
from sto_scheduler_core.duration import parse_iso_duration_seconds

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic-basic.mspdi.xml"


class DurationTests(unittest.TestCase):
    def test_mspdi_duration(self) -> None:
        self.assertEqual(parse_iso_duration_seconds("PT4H30M0S"), 16200)
        self.assertEqual(parse_iso_duration_seconds("PT0H0M0S"), 0)
        self.assertEqual(parse_iso_duration_seconds("P1DT2H"), 93600)


class MspdiImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = import_mspdi(FIXTURE)

    def test_inventory_and_hierarchy(self) -> None:
        inventory = self.document["source_inventory"]
        self.assertEqual(inventory["tasks"], 4)
        self.assertEqual(inventory["summary_tasks"], 2)
        self.assertEqual(inventory["leaf_activities"], 2)
        self.assertEqual(inventory["milestones"], 1)
        self.assertEqual(inventory["relationships"], 1)
        self.assertEqual(inventory["relationship_types"], {"FS": 1})
        self.assertEqual(self.document["wbs_nodes"][1]["parent_id"], "task:0")
        self.assertEqual(self.document["activities"][0]["parent_wbs_id"], "task:1")

    def test_relationship_semantics_are_explicit(self) -> None:
        relation = self.document["relationships"][0]
        self.assertEqual(relation["predecessor_ref"], "task:2")
        self.assertEqual(relation["successor_ref"], "task:3")
        self.assertEqual(relation["type"], "FS")
        self.assertEqual(relation["source_type_code"], 1)
        self.assertEqual(relation["lag_seconds"], 0)

    def test_custom_fields_and_extensions_are_preserved(self) -> None:
        activity = self.document["activities"][0]
        self.assertEqual(activity["custom_fields"][0]["field_id"], "188743740")
        self.assertEqual(activity["custom_fields"][0]["value"], "6183209")
        payload_names = {
            extension["payload"]["name"]
            for extension in self.document["vendor_extensions"]
            if extension["owner_ref"] == "task:2"
        }
        self.assertIn("TimephasedData", payload_names)
        self.assertIn("SyntheticUnsupported", payload_names)

    def test_calendars_resources_assignments_and_baseline(self) -> None:
        self.assertEqual(len(self.document["calendars"]), 1)
        self.assertEqual(self.document["calendars"][0]["week_days"][1]["working_times"][0]["from"], "08:00:00")
        self.assertEqual(len(self.document["resources"]), 2)
        self.assertEqual(self.document["resources"][1]["group"], "Mechanical")
        self.assertEqual(len(self.document["assignments"]), 1)
        self.assertEqual(self.document["assignments"][0]["task_ref"], "task:2")
        self.assertEqual(self.document["assignments"][0]["resource_ref"], "resource:1")
        self.assertEqual(len(self.document["baselines"]), 1)

    def test_repeated_import_is_deterministic(self) -> None:
        first = canonical_sha256(self.document)
        second = canonical_sha256(import_mspdi(FIXTURE))
        self.assertEqual(first, second)

    def test_validator_accepts_document(self) -> None:
        report = validate_canonical_schedule(self.document)
        self.assertTrue(report.valid, report.errors)

    def test_sanitized_inventory_omits_names(self) -> None:
        inventory = inventory_mspdi(FIXTURE)
        serialized = json.dumps(inventory)
        self.assertNotIn("Execute work", serialized)
        self.assertNotIn("Crew A", serialized)
        self.assertEqual(inventory["native_project_validation"], "not_executed")

    def test_missing_relationship_target_fails_validation(self) -> None:
        copy = json.loads(json.dumps(self.document))
        copy["relationships"][0]["predecessor_ref"] = "task:999"
        report = validate_canonical_schedule(copy)
        self.assertFalse(report.valid)
        self.assertTrue(any("missing predecessor" in item for item in report.errors))

    def test_canonical_document_can_be_round_tripped_through_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.json"
            path.write_text(json.dumps(self.document), encoding="utf-8")
            reloaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(canonical_sha256(self.document), canonical_sha256(reloaded))


if __name__ == "__main__":
    unittest.main()
