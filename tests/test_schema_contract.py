from __future__ import annotations

import json
import unittest
from pathlib import Path

from sto_scheduler_core import import_mspdi, validate_canonical_schedule

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-basic.mspdi.xml"
SCHEMA_PATH = ROOT / "schemas" / "canonical-schedule-v0.1.schema.json"


class CanonicalSchemaContractTests(unittest.TestCase):
    """Exercise the repository-owned top-level JSON Schema contract.

    This deliberately uses only the Python standard library. It is not a full
    Draft 2020-12 evaluator. It prevents the checked-in schema, importer output
    and custom validator from silently drifting apart at the top-level boundary.
    """

    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.document = import_mspdi(FIXTURE)

    def test_schema_and_importer_top_level_contract_match(self) -> None:
        required = set(self.schema["required"])
        properties = set(self.schema["properties"])
        document_keys = set(self.document)
        self.assertEqual(required, properties)
        self.assertEqual(document_keys, properties)
        self.assertFalse(self.schema["additionalProperties"])

    def test_schema_constants_and_required_source_fields_match(self) -> None:
        properties = self.schema["properties"]
        self.assertEqual(
            self.document["schema_version"], properties["schema_version"]["const"]
        )
        source_schema = properties["source"]
        source = self.document["source"]
        for key in source_schema["required"]:
            self.assertIn(key, source)
        for key in ("system", "format", "namespace"):
            self.assertEqual(source[key], source_schema["properties"][key]["const"])
        self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
        self.assertGreater(source["byte_length"], 0)
        self.assertEqual(source["identity_scope"], "document-local-v0.1")
        self.assertEqual(source["document_key"], f"sha256:{source['sha256']}")
        self.assertEqual(source["durable_cross_snapshot_identity"], "not_implemented")

    def test_schema_entity_collections_and_custom_validator_agree(self) -> None:
        collection_names = (
            "wbs_nodes",
            "work_packages",
            "activities",
            "relationships",
            "calendars",
            "resources",
            "assignments",
            "baselines",
            "custom_field_definitions",
            "vendor_extensions",
        )
        for name in collection_names:
            self.assertEqual(self.schema["properties"][name]["type"], "array")
            self.assertIsInstance(self.document[name], list)
            for item in self.document[name]:
                self.assertIsInstance(item.get("id"), str)
                self.assertTrue(item["id"])
        report = validate_canonical_schedule(self.document)
        self.assertTrue(report.valid, report.errors)


if __name__ == "__main__":
    unittest.main()
