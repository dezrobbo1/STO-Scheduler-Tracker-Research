from __future__ import annotations

from contextlib import contextmanager
import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Iterator
from xml.etree import ElementTree as ET

from sto.legacy import (
    MSPDI_NAMESPACE,
    MspdiImportError,
    canonical_sha256,
    import_mspdi,
    inventory_mspdi,
    validate_canonical_schedule,
)
from sto.legacy.duration import parse_iso_duration_seconds

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic-basic.mspdi.xml"
NS = {"p": MSPDI_NAMESPACE}


def _task_by_uid(tree: ET.ElementTree, uid: int) -> ET.Element:
    for task in tree.getroot().findall("p:Tasks/p:Task", NS):
        uid_element = task.find("p:UID", NS)
        if uid_element is not None and uid_element.text == str(uid):
            return task
    raise AssertionError(f"Synthetic fixture has no task UID {uid}")


def _assignment_by_uid(tree: ET.ElementTree, uid: int) -> ET.Element:
    for assignment in tree.getroot().findall("p:Assignments/p:Assignment", NS):
        uid_element = assignment.find("p:UID", NS)
        if uid_element is not None and uid_element.text == str(uid):
            return assignment
    raise AssertionError(f"Synthetic fixture has no assignment UID {uid}")


def _set_child_text(element: ET.Element, name: str, value: str) -> None:
    child = element.find(f"p:{name}", NS)
    if child is None:
        child = ET.SubElement(element, f"{{{MSPDI_NAMESPACE}}}{name}")
    child.text = value


@contextmanager
def _mutated_fixture(
    mutation: Callable[[ET.ElementTree], None],
) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as directory:
        tree = ET.parse(FIXTURE)
        mutation(tree)
        path = Path(directory) / "mutated.mspdi.xml"
        ET.register_namespace("", MSPDI_NAMESPACE)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        yield path


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
        self.assertFalse(self.document["wbs_nodes"][1]["milestone_source"])

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
        boundary = self.document["compatibility"]["preservation_boundary"]
        self.assertIn("not byte-for-byte XML preservation", boundary)
        self.assertIn("original source XML remains", boundary)

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

    def test_identity_scope_is_document_local_and_explicit(self) -> None:
        source = self.document["source"]
        self.assertEqual(source["identity_scope"], "document-local-v0.1")
        self.assertEqual(source["document_key"], f"sha256:{source['sha256']}")
        self.assertEqual(source["durable_cross_snapshot_identity"], "not_implemented")
        self.assertIn("document-local", self.document["compatibility"]["identity_boundary"])

    def test_summary_milestone_state_is_preserved(self) -> None:
        def mutation(tree: ET.ElementTree) -> None:
            _set_child_text(_task_by_uid(tree, 1), "Milestone", "1")

        with _mutated_fixture(mutation) as path:
            document = import_mspdi(path)
        summary = next(item for item in document["wbs_nodes"] if item["id"] == "task:1")
        self.assertTrue(summary["milestone_source"])
        self.assertEqual(document["source_inventory"]["summary_milestones"], 1)
        self.assertEqual(document["source_inventory"]["milestones"], 2)

    def test_unknown_assignment_resource_fails_closed(self) -> None:
        def mutation(tree: ET.ElementTree) -> None:
            _set_child_text(_assignment_by_uid(tree, 1), "ResourceUID", "999")

        with _mutated_fixture(mutation) as path:
            with self.assertRaisesRegex(MspdiImportError, "unknown ResourceUID 999"):
                import_mspdi(path)

    def test_skipped_outline_level_fails_closed(self) -> None:
        def mutation(tree: ET.ElementTree) -> None:
            _set_child_text(_task_by_uid(tree, 2), "OutlineLevel", "3")

        with _mutated_fixture(mutation) as path:
            with self.assertRaisesRegex(MspdiImportError, "no preceding summary parent"):
                import_mspdi(path)

    def test_validator_rejects_missing_expected_outline_parent(self) -> None:
        copy = json.loads(json.dumps(self.document))
        activity = next(item for item in copy["activities"] if item["id"] == "task:2")
        activity["outline_level"] = 3
        activity["parent_wbs_id"] = None
        report = validate_canonical_schedule(copy)
        self.assertFalse(report.valid)
        self.assertTrue(any("requires a summary parent" in item for item in report.errors))

    def test_validator_remains_compatible_with_v0_1_optional_additions(self) -> None:
        legacy = json.loads(json.dumps(self.document))
        legacy["importer_profile"] = "mspdi-import-v0.1"
        for key in (
            "identity_scope",
            "document_key",
            "durable_cross_snapshot_identity",
        ):
            legacy["source"].pop(key)
        for node in legacy["wbs_nodes"]:
            node.pop("milestone_source")
        report = validate_canonical_schedule(legacy)
        self.assertTrue(report.valid, report.errors)


if __name__ == "__main__":
    unittest.main()
