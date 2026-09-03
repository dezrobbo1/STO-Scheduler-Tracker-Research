"""A UID match with a changed GUID is a match that says so.

Raised in review of PR 22 as a conflict: a deleted row whose UID is reused by a
different row would be matched on the UID and both GUIDs bound to one canonical
identity. Measured on the only real snapshot pair, the premise fails the other
way round -- Microsoft Project regenerated every task GUID between saves while
every UID kept its work-order key, so a changed GUID on a matched UID is the
ordinary case for that source. Treating it as a conflict matched nothing.

What survives of the finding: the change must be visible, not silently
accumulated. Every entry says whether its GUID moved and the report counts them.
"""

from __future__ import annotations

import unittest

from sto.core.model.enums import EntityKind, ReconciliationOutcome, SourceSystem
from sto.core.model.ids import IdentityMap

GUID_A = "aaaaaaaa-0000-0000-0000-000000000001"
GUID_B = "bbbbbbbb-0000-0000-0000-000000000002"


def _fresh() -> IdentityMap:
    return IdentityMap(schedule_id="proj", system=SourceSystem.MICROSOFT_PROJECT)


class GuidChangeTests(unittest.TestCase):
    def test_a_uid_match_with_a_changed_guid_is_reported_as_such(self):
        identity = _fresh()
        first, _ = identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_A)

        again, entry = identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_B)

        self.assertEqual(again, first)
        self.assertEqual(entry.outcome, ReconciliationOutcome.MATCHED)
        self.assertTrue(entry.guid_changed)
        self.assertEqual(identity.guid_of[first], GUID_B)

    def test_both_guids_still_rekey_the_row(self):
        """An older export path may present the earlier GUID again."""

        identity = _fresh()
        first, _ = identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_A)
        identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_B)

        by_old, old_entry = identity.resolve(EntityKind.ACTIVITY, "8", guid=GUID_A)
        self.assertEqual(by_old, first)
        self.assertEqual(old_entry.outcome, ReconciliationOutcome.REKEYED)

    def test_an_unchanged_or_absent_guid_is_not_a_change(self):
        identity = _fresh()
        identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_A)

        _, same = identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_A)
        _, none = identity.resolve(EntityKind.ACTIVITY, "1")
        _, learned = identity.resolve(EntityKind.ACTIVITY, "2", guid=GUID_B)

        self.assertFalse(same.guid_changed)
        self.assertFalse(none.guid_changed)
        self.assertFalse(learned.guid_changed)

    def test_the_current_guid_survives_a_round_trip(self):
        identity = _fresh()
        first, _ = identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_A)
        identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_B)

        reloaded = IdentityMap.from_dict(identity.to_dict())

        self.assertEqual(reloaded.guid_of[first], GUID_B)
        _, entry = reloaded.resolve(EntityKind.ACTIVITY, "1", guid=GUID_B)
        self.assertFalse(entry.guid_changed)
        _, entry = reloaded.resolve(EntityKind.ACTIVITY, "1", guid=GUID_A)
        self.assertTrue(entry.guid_changed)

    def test_a_map_written_before_guid_of_existed_still_loads(self):
        identity = _fresh()
        first, _ = identity.resolve(EntityKind.ACTIVITY, "1", guid=GUID_A)
        payload = identity.to_dict()
        del payload["guid_of"]

        reloaded = IdentityMap.from_dict(payload)

        self.assertEqual(reloaded.guid_of[first], GUID_A)


if __name__ == "__main__":
    unittest.main()
