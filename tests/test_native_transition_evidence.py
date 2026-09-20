from __future__ import annotations

import unittest

from tests.native_transition_evidence import (
    DOCUMENTED_COMPLETION_CHANGE,
    FIELD_NAMES,
    classify_native_transition,
)


def row(**changes: object) -> tuple[object, ...]:
    values = {name: "same" for name in FIELD_NAMES}
    values.update(changes)
    return tuple(values[name] for name in FIELD_NAMES)


class NativeTransitionEvidenceClassifierTests(unittest.TestCase):
    def test_unchanged_input_is_unchanged(self):
        summary = classify_native_transition(
            {"control": row()},
            {"control": row()},
            documented_completion_uids=frozenset(),
        )
        self.assertEqual(summary.unchanged_common_rows, 1)
        self.assertEqual(summary.unresolved_rows, 0)

    def test_exact_documented_completion_is_expected(self):
        summary = classify_native_transition(
            {"edited": row()},
            {"edited": row(**{field: "changed" for field in DOCUMENTED_COMPLETION_CHANGE})},
            documented_completion_uids=frozenset({"edited"}),
        )
        self.assertEqual(summary.documented_completion_rows, 1)
        self.assertEqual(summary.unexplained_changed_common_rows, 0)

    def test_seeded_extra_change_is_unexplained_even_on_an_edited_row(self):
        changes = {field: "changed" for field in DOCUMENTED_COMPLETION_CHANGE}
        changes["early_start"] = "also changed"
        summary = classify_native_transition(
            {"edited": row()},
            {"edited": row(**changes)},
            documented_completion_uids=frozenset({"edited"}),
        )
        self.assertEqual(summary.documented_completion_rows, 0)
        self.assertEqual(summary.unexplained_changed_common_rows, 1)

    def test_start_finish_and_early_fields_are_not_interchanged(self):
        summary = classify_native_transition(
            {"row": row()},
            {"row": row(start="changed", finish="changed")},
            documented_completion_uids=frozenset(),
        )
        self.assertEqual(
            dict(summary.field_change_counts), {"start": 1, "finish": 1}
        )
        self.assertNotIn("early_start", dict(summary.field_change_counts))
        self.assertNotIn("early_finish", dict(summary.field_change_counts))

    def test_added_removed_and_changed_totals_reconcile(self):
        summary = classify_native_transition(
            {"same": row(), "changed": row(), "removed": row()},
            {"same": row(), "changed": row(late_start="changed"), "added": row()},
            documented_completion_uids=frozenset(),
        )
        self.assertEqual(summary.common_rows, 2)
        self.assertEqual(summary.unchanged_common_rows, 1)
        self.assertEqual(summary.unexplained_changed_common_rows, 1)
        self.assertEqual(summary.before_only_rows, 1)
        self.assertEqual(summary.after_only_rows, 1)
        self.assertEqual(summary.unresolved_rows, 3)

    def test_wrong_row_shape_fails(self):
        with self.assertRaisesRegex(ValueError, "field contract"):
            classify_native_transition(
                {"row": ("too short",)},
                {"row": ("too short",)},
                documented_completion_uids=frozenset(),
            )


if __name__ == "__main__":
    unittest.main()
