from __future__ import annotations

import json
import unittest
from pathlib import Path

from sto.legacy import import_mspdi

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic-basic.mspdi.xml"
SCHEMA_DIR = Path(__file__).parents[1] / "schemas"
HISTORICAL_SCHEMA = SCHEMA_DIR / "canonical-schedule-v0.1.schema.json"
HARDENED_SCHEMA = SCHEMA_DIR / "canonical-schedule-v0.1.1.schema.json"


class HardenedSchemaContractTests(unittest.TestCase):
    def test_dedicated_schema_matches_importer_output(self) -> None:
        document = import_mspdi(FIXTURE)
        schema = json.loads(HARDENED_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(schema["properties"]["schema_version"]["const"], document["schema_version"])
        self.assertEqual(schema["properties"]["importer_profile"]["const"], document["importer_profile"])
        self.assertEqual(set(schema["required"]), set(document))

        source_schema = schema["properties"]["source"]
        self.assertTrue(set(source_schema["required"]).issubset(document["source"]))
        for field in (
            "system",
            "format",
            "namespace",
            "identity_scope",
            "durable_cross_snapshot_identity",
        ):
            self.assertEqual(source_schema["properties"][field]["const"], document["source"][field])

    def test_historical_v01_schema_remains_immutable(self) -> None:
        historical = json.loads(HISTORICAL_SCHEMA.read_text(encoding="utf-8"))
        hardened = json.loads(HARDENED_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(historical["title"], "STO Canonical Schedule v0.1")
        self.assertEqual(historical["properties"]["schema_version"]["const"], "0.1.0")
        self.assertEqual(historical["properties"]["importer_profile"], {"type": "string"})
        self.assertEqual(
            historical["properties"]["source"]["required"],
            ["system", "format", "namespace", "sha256", "byte_length"],
        )
        self.assertNotIn(
            "identity_scope",
            historical["properties"]["source"]["properties"],
        )
        self.assertEqual(hardened["properties"]["schema_version"]["const"], "0.1.1")
        self.assertNotEqual(historical["properties"], hardened["properties"])


if __name__ == "__main__":
    unittest.main()
