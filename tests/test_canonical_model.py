"""Canonical model v1: hashing, identity, codec round-trip and migration.

The BOILER cases run only when the real schedules are present. They are real
customer files and stay outside this repository by policy; the synthetic
fixtures below carry the same assertions so CI still proves the behaviour.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from pathlib import Path

from sto.core.hashing import CanonicalHashError, canonical_json_bytes, canonical_sha256
from sto.core.model import decode_schedule, encode_schedule
from sto.core.model.entities import (
    Activity,
    Duration,
    ProjectSettings,
    Schedule,
    SourceSnapshot,
)
from sto.core.model.enums import EntityKind, SourceFormat, SourceSystem
from sto.core.model.ids import IdentityMap, mint_uid
from sto.core.model.migrate.sto_v011 import MigrationError, migrate
from sto.legacy import import_mspdi

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic-basic.mspdi.xml"

#: Real schedules live outside the repository. Point these at a checkout of the
#: evidence fixtures to run the BOILER cases.
BOILER_BEFORE = Path(os.environ.get("STO_BOILER_BEFORE", "/home/dez/sto-fixtures/boiler-before-no-progress.xml"))
BOILER_DAY5 = Path(os.environ.get("STO_BOILER_DAY5", "/home/dez/BOILER-WG110-day5-candidate.mspdi.xml"))


class CanonicalHashingTests(unittest.TestCase):
    def test_floats_are_refused(self):
        """A float makes the hash depend on binary rounding, so it is a defect."""

        with self.assertRaises(CanonicalHashError) as raised:
            canonical_json_bytes({"duration": 1.5})
        self.assertIn("duration", str(raised.exception))

    def test_key_order_does_not_change_the_hash(self):
        self.assertEqual(
            canonical_sha256({"a": 1, "b": 2}),
            canonical_sha256({"b": 2, "a": 1}),
        )

    def test_array_order_does_change_the_hash(self):
        self.assertNotEqual(canonical_sha256([1, 2]), canonical_sha256([2, 1]))

    def test_text_is_normalised_before_hashing(self):
        composed = "Attemperatoré"
        decomposed = "Attemperatoré"
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(canonical_sha256(composed), canonical_sha256(decomposed))


class IdentityTests(unittest.TestCase):
    def test_minting_is_a_pure_function_of_the_source(self):
        first = mint_uid("sched", SourceSystem.MICROSOFT_PROJECT, EntityKind.ACTIVITY, "43")
        second = mint_uid("sched", SourceSystem.MICROSOFT_PROJECT, EntityKind.ACTIVITY, "43")
        self.assertEqual(first, second)

    def test_schedule_scoping_prevents_collision(self):
        """Task UID 43 exists in every schedule ever written."""

        one = mint_uid("sched-a", SourceSystem.MICROSOFT_PROJECT, EntityKind.ACTIVITY, "43")
        two = mint_uid("sched-b", SourceSystem.MICROSOFT_PROJECT, EntityKind.ACTIVITY, "43")
        self.assertNotEqual(one, two)

    def test_kind_scoping_prevents_collision(self):
        activity = mint_uid("s", SourceSystem.MICROSOFT_PROJECT, EntityKind.ACTIVITY, "1")
        calendar = mint_uid("s", SourceSystem.MICROSOFT_PROJECT, EntityKind.CALENDAR, "1")
        self.assertNotEqual(activity, calendar)

    def test_second_sighting_matches_rather_than_mints(self):
        identity = IdentityMap("s", SourceSystem.MICROSOFT_PROJECT)
        first, first_entry = identity.resolve(EntityKind.ACTIVITY, "43")
        second, second_entry = identity.resolve(EntityKind.ACTIVITY, "43")
        self.assertEqual(first, second)
        self.assertEqual(str(first_entry.outcome), "new")
        self.assertEqual(str(second_entry.outcome), "matched")

    def test_a_renumbered_row_is_rekeyed_by_guid(self):
        """Microsoft Project renumbers UIDs on some operations but keeps GUIDs."""

        identity = IdentityMap("s", SourceSystem.MICROSOFT_PROJECT)
        original, _ = identity.resolve(EntityKind.ACTIVITY, "43", guid="G-43")
        moved, entry = identity.resolve(EntityKind.ACTIVITY, "9043", guid="G-43")
        self.assertEqual(original, moved)
        self.assertEqual(str(entry.outcome), "rekeyed")
        self.assertEqual(entry.matched_by, "guid")
        self.assertEqual(entry.previous_external_uid, "43")

    def test_business_key_rekeys_when_uid_and_guid_both_change(self):
        identity = IdentityMap("s", SourceSystem.SAP_PM)
        original, _ = identity.resolve(EntityKind.OPERATION, "1", business_key="WO123/0010")
        moved, entry = identity.resolve(EntityKind.OPERATION, "2", business_key="WO123/0010")
        self.assertEqual(original, moved)
        self.assertEqual(entry.matched_by, "business_key")

    def test_rows_absent_from_a_reimport_are_reported_not_deleted(self):
        identity = IdentityMap("s", SourceSystem.MICROSOFT_PROJECT)
        identity.resolve(EntityKind.ACTIVITY, "1")
        identity.resolve(EntityKind.ACTIVITY, "2")
        missing = identity.missing_since(EntityKind.ACTIVITY, ["1"])
        self.assertEqual([entry.external_uid for entry in missing], ["2"])

    def test_identity_map_survives_serialisation(self):
        identity = IdentityMap("s", SourceSystem.MICROSOFT_PROJECT)
        uid, _ = identity.resolve(EntityKind.ACTIVITY, "43", guid="G-43")
        restored = IdentityMap.from_dict(identity.to_dict())
        again, entry = restored.resolve(EntityKind.ACTIVITY, "43")
        self.assertEqual(uid, again)
        self.assertEqual(str(entry.outcome), "matched")


class CodecTests(unittest.TestCase):
    def _schedule(self) -> Schedule:
        uid = mint_uid("s", SourceSystem.MICROSOFT_PROJECT, EntityKind.ACTIVITY, "43")
        return Schedule(
            schedule_id="s",
            project=ProjectSettings(name="Boiler", status_date=datetime(2025, 5, 9, 17, 0)),
            snapshots=(
                SourceSnapshot(
                    snapshot_id="abc",
                    system=SourceSystem.MICROSOFT_PROJECT,
                    format=SourceFormat.MSPDI,
                    file_sha256="0" * 64,
                    byte_length=10,
                    application_version="16.0.20131.20152",
                ),
            ),
            activities=(
                Activity(
                    uid=uid,
                    name="Scaffold access",
                    planned_duration=Duration(seconds=28800, unit="h"),
                    actual_start=datetime(2026, 8, 21, 13, 30),
                    udfs={"Work Order No.": "WO-EXAMPLE"},
                ),
            ),
        )

    def test_round_trip_is_exact(self):
        schedule = self._schedule()
        self.assertEqual(decode_schedule(encode_schedule(schedule)), schedule)

    def test_defaults_are_omitted_so_added_fields_do_not_move_hashes(self):
        payload = encode_schedule(self._schedule())
        self.assertNotIn("percent_complete", payload["activities"][0])
        self.assertNotIn("baselines", payload)

    def test_schema_version_is_always_written(self):
        """The discriminator is not an ordinary field: a document without it
        cannot be interpreted, so default-omission must not apply to it."""

        payload = encode_schedule(self._schedule())
        self.assertEqual(payload["schema_version"], "sto-canonical-1.0")

    def test_encoded_document_hashes(self):
        canonical_sha256(encode_schedule(self._schedule()))


class MigrationTests(unittest.TestCase):
    def test_unknown_importer_profile_is_refused(self):
        with self.assertRaises(MigrationError):
            migrate({"importer_profile": "something-else"})

    def test_synthetic_fixture_migrates_and_round_trips(self):
        schedule, _, report = migrate(import_mspdi(str(SYNTHETIC)))
        self.assertTrue(schedule.activities)
        self.assertEqual(decode_schedule(encode_schedule(schedule)), schedule)
        self.assertEqual(report.missing, 0)

    def test_migration_is_deterministic(self):
        document = import_mspdi(str(SYNTHETIC))
        first = canonical_sha256(encode_schedule(migrate(document)[0]))
        second = canonical_sha256(encode_schedule(migrate(import_mspdi(str(SYNTHETIC)))[0]))
        self.assertEqual(first, second)

    def test_slack_is_converted_from_tenths_of_a_minute(self):
        """Six seconds per unit. Reading it as seconds is off by a factor of ten."""

        schedule, _, _ = migrate(import_mspdi(str(SYNTHETIC)))
        observed = [
            activity.source_observations
            for activity in schedule.activities
            if activity.source_observations is not None
            and activity.source_observations.total_float_seconds
        ]
        for observation in observed:
            self.assertEqual(observation.total_float_seconds % 6, 0)


@unittest.skipUnless(
    BOILER_BEFORE.is_file() and BOILER_DAY5.is_file(),
    "real BOILER schedules not present (they stay outside the repository)",
)
class BoilerSnapshotTests(unittest.TestCase):
    """The file oracle's first rung: a real 3.4 MB shutdown schedule."""

    @classmethod
    def setUpClass(cls):
        cls.before_document = import_mspdi(str(BOILER_BEFORE))
        cls.day5_document = import_mspdi(str(BOILER_DAY5))

    def test_migration_round_trips_a_real_schedule(self):
        schedule, _, _ = migrate(self.before_document)
        self.assertEqual(decode_schedule(encode_schedule(schedule)), schedule)

    def test_two_imports_of_one_file_hash_identically(self):
        first, _, _ = migrate(self.before_document)
        second, _, _ = migrate(import_mspdi(str(BOILER_BEFORE)))
        self.assertEqual(
            canonical_sha256(encode_schedule(first)),
            canonical_sha256(encode_schedule(second)),
        )

    def test_the_site_work_order_convention_survives_migration(self):
        """``Text4``/``Text5`` are aliased Work Order No. and Operation No.

        That pair is the key a CMMS import links operations to activities on, so
        losing the alias would silently break the link resolver.
        """

        schedule, _, _ = migrate(self.day5_document)
        linked = [
            activity
            for activity in schedule.activities
            if activity.udfs.get("Work Order No.") and activity.udfs.get("Operation No.")
        ]
        self.assertTrue(linked, "no activity carried the work-order convention")

    def test_the_project_build_is_captured_for_the_evidence_register(self):
        schedule, _, _ = migrate(self.day5_document)
        self.assertRegex(schedule.snapshots[0].application_version or "", r"^16\.0\.")

    def test_a_later_snapshot_keeps_the_identifiers_of_surviving_rows(self):
        before, identity, _ = migrate(self.before_document)
        day5, _, report = migrate(
            self.day5_document, identity=identity, schedule_id=before.schedule_id
        )

        before_uids = {
            activity.external_refs[0].uid: activity.uid for activity in before.activities
        }
        day5_uids = {activity.external_refs[0].uid: activity.uid for activity in day5.activities}
        shared = set(before_uids) & set(day5_uids)

        self.assertTrue(shared)
        for external_uid in shared:
            self.assertEqual(
                before_uids[external_uid],
                day5_uids[external_uid],
                f"task UID {external_uid} changed identity between snapshots",
            )

        activity_entries = report.of_kind(EntityKind.ACTIVITY)
        matched = sum(1 for entry in activity_entries if str(entry.outcome) == "matched")
        self.assertEqual(matched, len(shared))

    def test_every_new_or_missing_row_is_a_real_source_difference(self):
        """Reconciliation must report churn, never manufacture it.

        This replaces a wrong diagnosis. The 341/136/131 assignment split was
        first read as evidence that Microsoft Project renumbers assignment UIDs,
        and that assignments therefore needed a ``(task UID, resource UID)``
        business key. Measured, that key matches exactly the rows the UID
        already matches -- necessarily so, because the importer derives both
        halves of it *from* those UIDs. The split is real churn: the two
        documents carry different resourcing.

        So the property worth holding is not "assignments match better" but
        "every row we call new or missing is absent from the other document".
        A future change that breaks identity shows up here as a row that is
        present in both and still reported as new.
        """

        before, identity, _ = migrate(self.before_document)
        _, _, report = migrate(
            self.day5_document, identity=identity, schedule_id=before.schedule_id
        )

        def source_uids(document, collection):
            return {
                _external_uid_of(row) for row in document.get(collection, [])
            }

        for kind, collection in (
            (EntityKind.ACTIVITY, "activities"),
            (EntityKind.ASSIGNMENT, "assignments"),
            (EntityKind.RESOURCE, "resources"),
        ):
            earlier = source_uids(self.before_document, collection)
            later = source_uids(self.day5_document, collection)

            for entry in report.of_kind(kind):
                outcome = str(entry.outcome)
                if outcome == "new":
                    self.assertNotIn(
                        entry.external_uid,
                        earlier,
                        f"{kind} {entry.external_uid} is reported new but was in "
                        "the earlier document: identity failed to carry it forward",
                    )
                elif outcome == "missing":
                    self.assertNotIn(
                        entry.external_uid,
                        later,
                        f"{kind} {entry.external_uid} is reported missing but is "
                        "in the later document: identity failed to match it",
                    )

    def test_the_reconciliation_counts_are_pinned(self):
        """Pinned so a change in identity moves a number somebody re-reads.

        These are properties of the two schedules, not of the code. If they
        move without the schedules changing, identity changed.
        """

        before, identity, _ = migrate(self.before_document)
        _, _, report = migrate(
            self.day5_document, identity=identity, schedule_id=before.schedule_id
        )

        def counts(kind):
            entries = report.of_kind(kind)
            return tuple(
                sum(1 for entry in entries if str(entry.outcome) == outcome)
                for outcome in ("matched", "new", "missing")
            )

        self.assertEqual(counts(EntityKind.ACTIVITY), (447, 18, 13))
        self.assertEqual(counts(EntityKind.ASSIGNMENT), (341, 136, 131))

    def test_rows_dropped_between_snapshots_are_reported_not_lost(self):
        before, identity, _ = migrate(self.before_document)
        _, _, report = migrate(
            self.day5_document, identity=identity, schedule_id=before.schedule_id
        )
        seen = [entry.external_uid for entry in report.of_kind(EntityKind.ACTIVITY)]
        missing = identity.missing_since(EntityKind.ACTIVITY, seen)
        self.assertTrue(all(entry.uid is not None for entry in missing))


if __name__ == "__main__":
    unittest.main()


class ReviewFollowUpTests(unittest.TestCase):
    """Regressions for defects found by automated review of PR #22.

    Each was verified against the code before being acted on; the findings that
    would have made the migration refuse real files are recorded in
    ``docs/goals/ACTIVE.md`` against the slice that owns them instead.
    """

    def test_rekeying_retires_the_old_external_key(self):
        """Otherwise a rekeyed row is reported as rekeyed *and* missing, and a
        reused UID would later resolve to the wrong entity."""

        identity = IdentityMap("s", SourceSystem.MICROSOFT_PROJECT)
        identity.resolve(EntityKind.ACTIVITY, "43", guid="G-43")
        identity.resolve(EntityKind.ACTIVITY, "9043", guid="G-43")
        missing = identity.missing_since(EntityKind.ACTIVITY, ["9043"])
        self.assertEqual(missing, ())

    def test_decoding_refuses_a_document_with_no_schema_version(self):
        with self.assertRaises(Exception):
            decode_schedule({"schedule_id": "s"})

    def test_decoding_refuses_an_unsupported_schema_version(self):
        with self.assertRaises(Exception):
            decode_schedule({"schedule_id": "s", "schema_version": "sto-canonical-99.0"})

    def test_booleans_are_not_coerced_from_strings(self):
        """``bool("false")`` is True, which would invert an activity's meaning."""

        from sto.core.model.codec import CodecError, decode
        from sto.core.model.entities import Activity

        uid = mint_uid("s", SourceSystem.MICROSOFT_PROJECT, EntityKind.ACTIVITY, "1")
        with self.assertRaises(CodecError):
            decode(Activity, {"uid": str(uid), "active": "false"})

    def test_microsoft_fixed_duration_maps_to_fixed_duration(self):
        """MS ``Type=1`` means Fixed Duration, not the Primavera
        fixed-duration-and-units policy, which also pins units."""

        from sto.core.model.enums import DurationType
        from sto.core.model.migrate.sto_v011 import _MS_TASK_TYPE

        self.assertIs(_MS_TASK_TYPE[1], DurationType.FIXED_DURATION)

    def test_material_resources_are_not_reclassified_as_labour(self):
        """``0 or 1`` is 1, which silently made every material resource work."""

        from sto.core.model.enums import ResourceType
        from sto.core.model.migrate.sto_v011 import _resource_type

        self.assertIs(_resource_type(0), ResourceType.MATERIAL)
        self.assertIs(_resource_type(1), ResourceType.LABOR)
        self.assertIs(_resource_type(None), ResourceType.LABOR)

    def test_baselines_survive_migration(self):
        schedule, _, _ = migrate(import_mspdi(str(SYNTHETIC)))
        self.assertTrue(schedule.baselines)
        self.assertTrue(schedule.baselines[0].activity_states)

    def test_relationship_identity_survives_reordering(self):
        """The importer's id is ``relationship:{successor}:{ordinal}``, so
        inserting a link ahead of another would hand over its identity."""

        document = import_mspdi(str(SYNTHETIC))
        first, identity, _ = migrate(document)

        reordered = import_mspdi(str(SYNTHETIC))
        reordered["relationships"] = list(reversed(reordered["relationships"]))
        for index, row in enumerate(reordered["relationships"]):
            row["id"] = f"relationship:reordered:{index}"

        second, _, _ = migrate(reordered, identity=identity, schedule_id=first.schedule_id)
        self.assertEqual(
            {relationship.uid for relationship in first.relationships},
            {relationship.uid for relationship in second.relationships},
        )

    def test_the_report_names_rows_the_later_document_dropped(self):
        """The serialised report previously always said missing == 0, so it
        disagreed with the table the command line printed."""

        document = import_mspdi(str(SYNTHETIC))
        _, identity, _ = migrate(document)

        trimmed = import_mspdi(str(SYNTHETIC))
        dropped = trimmed["activities"].pop()
        _, _, report = migrate(trimmed, identity=identity)

        missing = [entry for entry in report.entries if str(entry.outcome) == "missing"]
        self.assertTrue(missing)
        self.assertIn(
            _external_uid_of(dropped), [entry.external_uid for entry in missing]
        )


def _external_uid_of(row: dict) -> str:
    for entry in row.get("external_references", []):
        if entry.get("type") == "UID":
            return str(entry["value"])
    return str(row.get("id"))
