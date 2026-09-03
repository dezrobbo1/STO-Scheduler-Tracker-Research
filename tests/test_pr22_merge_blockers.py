"""Regression coverage for the final merge blockers on PR #22."""

from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sto.cli import main
from sto.core.model.enums import (
    EntityKind,
    ResourceType,
    SourceSystem,
)
from sto.core.model.ids import IdentityMap
from sto.core.model.migrate.sto_v011 import (
    MigrationError,
    _duration_type,
    _resource_type,
    migrate,
)
from sto.legacy import import_mspdi

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic-basic.mspdi.xml"


def _set_external(row: dict, kind: str, value: str) -> None:
    for entry in row.get("external_references", []):
        if entry.get("type") == kind:
            entry["value"] = value
            return
    row.setdefault("external_references", []).append({"type": kind, "value": value})


class DurableIdentityBlockerTests(unittest.TestCase):
    def test_uuid_spelling_does_not_change_guid_identity(self):
        identity = IdentityMap("s", SourceSystem.MICROSOFT_PROJECT)
        original, _ = identity.resolve(
            EntityKind.ACTIVITY,
            "43",
            guid="{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}",
        )
        moved, entry = identity.resolve(
            EntityKind.ACTIVITY,
            "9043",
            guid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.assertEqual(original, moved)
        self.assertEqual(entry.matched_by, "guid")

    def test_external_uid_match_learns_a_later_guid(self):
        identity = IdentityMap("s", SourceSystem.MICROSOFT_PROJECT)
        original, _ = identity.resolve(EntityKind.ACTIVITY, "43")
        matched, _ = identity.resolve(
            EntityKind.ACTIVITY,
            "43",
            guid="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        )
        moved, entry = identity.resolve(
            EntityKind.ACTIVITY,
            "9043",
            guid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.assertEqual(original, matched)
        self.assertEqual(original, moved)
        self.assertEqual(entry.matched_by, "guid")

    def test_project_guid_case_does_not_change_fresh_canonical_identity(self):
        first_doc = import_mspdi(str(SYNTHETIC))
        second_doc = copy.deepcopy(first_doc)
        _set_external(
            first_doc["project"],
            "GUID",
            "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        )
        _set_external(
            second_doc["project"],
            "GUID",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        first, _, _ = migrate(first_doc)
        second, _, _ = migrate(second_doc)
        self.assertEqual(first.schedule_id, second.schedule_id)
        self.assertEqual(
            [activity.uid for activity in first.activities],
            [activity.uid for activity in second.activities],
        )

    def test_failed_migration_does_not_mutate_supplied_identity(self):
        identity = IdentityMap("s", SourceSystem.MICROSOFT_PROJECT)
        before = copy.deepcopy(identity.to_dict())
        document = import_mspdi(str(SYNTHETIC))
        document["activities"][0]["source_task_type"] = 999
        with self.assertRaises(MigrationError):
            migrate(document, identity=identity, schedule_id="s")
        self.assertEqual(identity.to_dict(), before)

    def test_relationship_identity_uses_resolved_endpoint_ids(self):
        document = import_mspdi(str(SYNTHETIC))
        relationship = document["relationships"][0]
        predecessor_ref = str(relationship["predecessor_ref"])
        predecessor = next(
            row for row in document["activities"] if str(row.get("id")) == predecessor_ref
        )
        stable_guid = "11111111-2222-3333-4444-555555555555"
        _set_external(predecessor, "GUID", stable_guid)

        first, identity, _ = migrate(document)
        first_rel_uid = first.relationships[0].uid

        later = copy.deepcopy(document)
        later_relationship = later["relationships"][0]
        old_ref = str(later_relationship["predecessor_ref"])
        later_predecessor = next(
            row for row in later["activities"] if str(row.get("id")) == old_ref
        )
        old_uid = next(
            str(entry["value"])
            for entry in later_predecessor["external_references"]
            if entry.get("type") == "UID"
        )
        new_uid = str(int(old_uid) + 10000)
        new_ref = f"task:{new_uid}"
        later_predecessor["id"] = new_ref
        _set_external(later_predecessor, "UID", new_uid)
        _set_external(later_predecessor, "GUID", stable_guid.upper())
        later_relationship["predecessor_ref"] = new_ref

        second, _, _ = migrate(later, identity=identity, schedule_id=first.schedule_id)
        self.assertIn(first_rel_uid, {item.uid for item in second.relationships})

    def test_removing_an_entire_entity_kind_reports_every_missing_row(self):
        document = import_mspdi(str(SYNTHETIC))
        _, identity, _ = migrate(document)
        expected = len(document["assignments"])
        later = copy.deepcopy(document)
        later["assignments"] = []
        _, _, report = migrate(later, identity=identity)
        self.assertEqual(
            len(
                [
                    entry
                    for entry in report.of_kind(EntityKind.ASSIGNMENT)
                    if str(entry.outcome) == "missing"
                ]
            ),
            expected,
        )


class SourceSemanticBlockerTests(unittest.TestCase):
    def test_cost_resource_stays_distinct_from_capacity_resources(self):
        self.assertIs(_resource_type(2), ResourceType.COST)

    def test_unknown_explicit_resource_type_is_rejected(self):
        with self.assertRaises(MigrationError):
            _resource_type(99)

    def test_unknown_explicit_task_type_is_rejected(self):
        with self.assertRaises(MigrationError):
            _duration_type(99)


class CanonicalCliBlockerTests(unittest.TestCase):
    def test_canonicalise_accepts_prior_identity_map(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            identity_path = directory_path / "identity.json"
            canonical_path = directory_path / "canonical.json"
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "canonicalise",
                        str(SYNTHETIC),
                        "--quiet",
                        "--identity-out",
                        str(identity_path),
                    ]
                )
                main(
                    [
                        "canonicalise",
                        str(SYNTHETIC),
                        "--quiet",
                        "--identity-in",
                        str(identity_path),
                        "--identity-out",
                        str(identity_path),
                        "--output",
                        str(canonical_path),
                    ]
                )
            self.assertEqual(
                json.loads(canonical_path.read_text(encoding="utf-8"))["schedule_id"],
                json.loads(identity_path.read_text(encoding="utf-8"))["schedule_id"],
            )

    def test_hard_link_output_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "schedule.xml"
            source.write_bytes(SYNTHETIC.read_bytes())
            hard_link = Path(directory) / "hard-link.xml"
            os.link(source, hard_link)
            original = source.read_bytes()
            with self.assertRaises(SystemExit):
                main(["canonicalise", str(source), "--output", str(hard_link)])
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
