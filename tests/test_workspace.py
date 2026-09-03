from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from calculation_fixture import _activity, _calendar, _document, _relationship
from sto.legacy import canonical_sha256, import_mspdi
from sto.legacy.workspace import (
    WORKSPACE_EXPORT_PROFILE,
    WORKSPACE_PROFILE,
    WorkspaceScenarioError,
    WorkspaceSession,
    _eligible_downstream_counts,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "synthetic-workspace-chain.mspdi.xml"
)


def _row(view: dict[str, object], activity_id: str) -> dict[str, object]:
    tasks = view["tasks"]
    assert isinstance(tasks, list)
    return next(item for item in tasks if item["id"] == activity_id)


class WorkspaceSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = WorkspaceSession.from_mspdi(FIXTURE)

    def test_import_builds_compact_ordered_hierarchy_and_recommendation(self) -> None:
        view = self.session.view()

        self.assertEqual(view["workspace_profile"], WORKSPACE_PROFILE)
        self.assertEqual(view["workspace_id"], self.session.workspace_id)
        self.assertEqual(view["revision"], 0)
        self.assertEqual(view["source"]["file_name"], FIXTURE.name)
        self.assertEqual(view["inventory"]["tasks"], 6)
        self.assertEqual(view["inventory"]["relationships"], 3)
        self.assertEqual(view["calculation"]["eligible_activities"], 4)
        self.assertEqual(view["scenario"]["moved_task_count"], 0)
        self.assertEqual(
            [item["id"] for item in view["tasks"]],
            ["task:0", "task:1", "task:2", "task:3", "task:4", "task:5"],
        )
        self.assertEqual(view["counts"]["tasks"], 6)
        self.assertEqual(view["counts"]["summary_tasks"], 2)
        self.assertEqual(view["counts"]["activities"], 4)
        self.assertEqual(view["counts"]["calculated_activities"], 4)
        self.assertEqual(view["counts"]["editable_activities"], 3)
        self.assertEqual(view["counts"]["changed_activities"], 0)

        root = _row(view, "task:0")
        package = _row(view, "task:1")
        first = _row(view, "task:2")
        milestone = _row(view, "task:5")
        self.assertEqual(root["kind"], "summary")
        self.assertIsNone(root["parent_id"])
        self.assertEqual(package["parent_id"], "task:0")
        self.assertEqual(first["parent_id"], "task:1")
        self.assertEqual(first["imported"]["start"], first["calculated"]["base_start"])
        self.assertEqual(first["imported"]["finish"], first["calculated"]["base_finish"])
        self.assertTrue(first["duration_editable"])
        self.assertFalse(milestone["duration_editable"])
        self.assertEqual(
            milestone["duration_edit_reasons"],
            ["MILESTONE_DURATION_OVERRIDE_UNSUPPORTED"],
        )
        self.assertEqual(
            view["recommended_editable_task"],
            {
                "activity_id": "task:2",
                "name": "Isolate equipment",
                "eligible_downstream_count": 3,
            },
        )
        self.assertEqual(view["recommended_task_id"], "task:2")

    def test_downstream_counts_are_unique_across_a_diamond(self) -> None:
        projection = {
            "activities": [
                {"id": activity_id} for activity_id in ("a", "b", "c", "d")
            ],
            "relationships": [
                {"predecessor_ref": "a", "successor_ref": "b"},
                {"predecessor_ref": "a", "successor_ref": "c"},
                {"predecessor_ref": "b", "successor_ref": "d"},
                {"predecessor_ref": "c", "successor_ref": "d"},
            ],
        }

        self.assertEqual(
            _eligible_downstream_counts(projection),
            {"a": 3, "b": 1, "c": 1, "d": 0},
        )

    def test_duration_override_moves_chain_and_reports_base_deltas(self) -> None:
        view = self.session.set_duration("task:2", 8 * 60 * 60)

        self.assertEqual(view["revision"], 1)
        self.assertEqual(view["counts"]["changed_activities"], 4)
        self.assertEqual(view["scenario"]["moved_task_count"], 4)
        self.assertEqual(
            view["scenario"]["duration_override"],
            {
                "activity_id": "task:2",
                "original_duration_seconds": 4 * 60 * 60,
                "duration_seconds": 8 * 60 * 60,
                "delta_seconds": 4 * 60 * 60,
            },
        )
        self.assertNotEqual(
            view["scenario"]["base_projection_sha256"],
            view["scenario"]["current_projection_sha256"],
        )

        first = _row(view, "task:2")
        second = _row(view, "task:3")
        third = _row(view, "task:4")
        milestone = _row(view, "task:5")
        self.assertEqual(first["duration"]["current_seconds"], 8 * 60 * 60)
        self.assertEqual(first["calculated"]["current_finish"], "2026-01-05T17:00:00")
        self.assertEqual(first["calculated"]["start_delta_seconds"], 0)
        self.assertEqual(first["calculated"]["finish_delta_seconds"], 5 * 60 * 60)
        self.assertEqual(second["calculated"]["current_start"], "2026-01-06T08:00:00")
        self.assertEqual(third["calculated"]["current_finish"], "2026-01-06T17:00:00")
        self.assertEqual(milestone["calculated"]["current_start"], "2026-01-06T17:00:00")
        self.assertTrue(
            all(item["calculated"]["changed"] for item in (first, second, third, milestone))
        )

    def test_new_override_replaces_the_previous_override_from_base(self) -> None:
        self.session.set_duration("task:2", 8 * 60 * 60)
        view = self.session.set_duration("task:3", 2 * 60 * 60)

        self.assertEqual(view["scenario"]["duration_override"]["activity_id"], "task:3")
        self.assertEqual(_row(view, "task:2")["duration"]["current_seconds"], 4 * 60 * 60)
        self.assertFalse(_row(view, "task:2")["duration"]["overridden"])
        self.assertTrue(_row(view, "task:3")["duration"]["overridden"])

    def test_reset_restores_exact_initial_state(self) -> None:
        initial = self.session.export_state()
        self.session.set_duration("task:2", 8 * 60 * 60)
        restored = self.session.reset()

        self.assertFalse(restored["scenario"]["active"])
        self.assertIsNone(restored["scenario"]["duration_override"])
        self.assertEqual(
            restored["scenario"]["base_projection_sha256"],
            restored["scenario"]["current_projection_sha256"],
        )
        restored_export = self.session.export_state()
        self.assertEqual(restored_export["revision"], 2)
        initial["revision"] = restored_export["revision"]
        self.assertEqual(restored_export, initial)

    def test_scenario_and_returned_views_do_not_mutate_source(self) -> None:
        document = import_mspdi(FIXTURE)
        original_hash = canonical_sha256(document)
        session = WorkspaceSession.from_document(document)

        first_view = session.set_duration("task:2", 8 * 60 * 60)
        first_view["tasks"][2]["name"] = "View mutation"
        self.assertEqual(session.view()["tasks"][2]["name"], "Isolate equipment")
        session.reset()
        self.assertEqual(canonical_sha256(document), original_hash)

    def test_caller_mutation_after_construction_cannot_change_workspace(self) -> None:
        document = import_mspdi(FIXTURE)
        session = WorkspaceSession.from_document(document, "original.xml")
        before = session.export_state()

        document["source"]["sha256"] = "0" * 64
        document["project"]["name"] = "Caller mutation"
        document["activities"][0]["name"] = "Caller mutation"
        document["relationships"].clear()

        self.assertEqual(session.export_state(), before)

    def test_export_is_deterministic_compact_and_document_scoped(self) -> None:
        first = self.session.export_state()
        second = self.session.export_state()

        self.assertEqual(first, second)
        json.dumps(first, allow_nan=False)
        self.assertEqual(first["export_profile"], WORKSPACE_EXPORT_PROFILE)
        self.assertEqual(first["source"]["identity_scope"], "document-local-v0.1")
        self.assertEqual(
            first["source"]["document_key"],
            f"sha256:{first['source']['sha256']}",
        )
        self.assertEqual(len(first["relationships"]), 3)
        self.assertTrue(
            all(item["calculation_supported"] for item in first["relationships"])
        )
        self.assertNotIn("vendor_extensions", first)
        self.assertNotIn("calendars", first)

        changed = self.session.set_duration("task:2", 8 * 60 * 60)
        active = self.session.export_state()
        self.assertTrue(active["scenario"]["active"])
        self.assertEqual(
            active["duration_overrides_seconds"], {"task:2": 8 * 60 * 60}
        )
        self.assertEqual(active["tasks"], changed["tasks"])
        self.assertNotEqual(
            active["scenario"]["base_calculation_sha256"],
            active["scenario"]["current_calculation_sha256"],
        )

    def test_ineligible_rows_remain_visible_with_profile_reasons(self) -> None:
        document = import_mspdi(FIXTURE)
        document = deepcopy(document)
        activity = next(item for item in document["activities"] if item["id"] == "task:3")
        activity["active"] = False
        session = WorkspaceSession.from_document(document)
        view = session.view()

        excluded = _row(view, "task:3")
        downstream = _row(view, "task:4")
        self.assertFalse(excluded["supported"])
        self.assertIn("ACTIVITY_INACTIVE", excluded["support_reasons"])
        self.assertFalse(downstream["supported"])
        self.assertIn("INELIGIBLE_PREDECESSOR", downstream["support_reasons"])
        self.assertEqual(view["counts"]["tasks"], 6)

        with self.assertRaises(WorkspaceScenarioError) as raised:
            session.set_duration("task:3", 8 * 60 * 60)
        self.assertEqual(raised.exception.code, "ACTIVITY_INELIGIBLE")
        self.assertIn(
            "ACTIVITY_INACTIVE", raised.exception.as_dict()["details"]["reason_codes"]
        )

    def test_override_rejects_invalid_targets_and_durations(self) -> None:
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value):
                with self.assertRaises(WorkspaceScenarioError) as raised:
                    self.session.set_duration("task:2", value)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.code, "DURATION_INVALID")

        cases = (
            ("task:0", "SUMMARY_TASK_UNSUPPORTED"),
            ("task:5", "MILESTONE_UNSUPPORTED"),
            ("task:999", "ACTIVITY_NOT_FOUND"),
        )
        for activity_id, code in cases:
            with self.subTest(activity_id=activity_id):
                with self.assertRaises(WorkspaceScenarioError) as raised:
                    self.session.set_duration(activity_id, 60 * 60)
                self.assertEqual(raised.exception.code, code)

    def test_calendar_exception_horizon_rejection_is_atomic(self) -> None:
        accepted = self.session.set_duration("task:2", 8 * 60 * 60)
        accepted_export = self.session.export_state()
        self.assertEqual(accepted["safe_scenario_horizon"]["finish"], "2026-01-06T17:00:00")

        with self.assertRaises(WorkspaceScenarioError) as raised:
            self.session.set_duration("task:2", 12 * 60 * 60)
        error = raised.exception
        self.assertEqual(error.code, "SCENARIO_OUTSIDE_SAFE_HORIZON")
        self.assertEqual(
            error.as_dict()["details"]["safe_horizon"]["finish"],
            "2026-01-06T17:00:00",
        )
        self.assertEqual(
            {item["activity_id"] for item in error.as_dict()["details"]["violations"]},
            {"task:4", "task:5"},
        )
        self.assertEqual(self.session.export_state(), accepted_export)

    def test_base_dates_do_not_expand_ignored_exception_horizon(self) -> None:
        ignored_exception = {
            "id": "exception:outside-source",
            "from": "2026-01-06T00:00:00",
            "to": "2026-01-06T23:59:59",
        }

        def activity(uid: int, calendar_uid: int):
            return _activity(
                uid,
                start="2026-01-05T08:00:00",
                finish="2026-01-05T16:00:00",
                duration_seconds=8 * 60 * 60,
                calendar_ref=f"calendar:{calendar_uid}",
            )

        document = _document(
            [activity(1, 2), activity(2, 2), activity(3, 1)],
            relationships=[_relationship(1, 1, 2)],
            calendars=[
                _calendar(
                    1,
                    [("08:00:00", "16:00:00")],
                    exceptions=[ignored_exception],
                ),
                _calendar(2, [("08:00:00", "16:00:00")]),
            ],
            project_start="2026-01-05T08:00:00",
            project_finish="2026-01-05T16:00:00",
        )
        session = WorkspaceSession.from_document(document)
        before = session.export_state()

        with self.assertRaises(WorkspaceScenarioError) as raised:
            session.set_duration("task:3", 12 * 60 * 60)

        self.assertEqual(
            raised.exception.code, "SCENARIO_OUTSIDE_SAFE_HORIZON"
        )
        self.assertEqual(
            {
                item["activity_id"]
                for item in raised.exception.details["violations"]
            },
            {"task:3"},
        )
        self.assertEqual(session.export_state(), before)


if __name__ == "__main__":
    unittest.main()
