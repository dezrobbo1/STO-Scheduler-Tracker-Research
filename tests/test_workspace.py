from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sto_scheduler_core.calculation_profile import CalculationProfileError
from sto_scheduler_core.mspdi import import_mspdi
from sto_scheduler_core.workspace import (
    ActivityNotEditableError,
    InvalidDurationError,
    ScheduleWorkspace,
    WorkspaceNotLoadedError,
)


FIXTURES = Path(__file__).parent / "fixtures"
CHAIN = FIXTURES / "prototype0-chain.mspdi.xml"


def _duration(seconds: int, raw: str) -> dict[str, object]:
    return {"parse_status": "parsed", "raw": raw, "seconds": seconds}


def _calendar_exception(
    identifier: str,
    start: str,
    finish: str,
    *,
    working: bool = False,
) -> dict[str, object]:
    return {
        "id": identifier,
        "from": start,
        "to": finish,
        "working": working,
        "working_times": [],
    }


class ScheduleWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = ScheduleWorkspace()
        self.baseline = self.workspace.load_mspdi(CHAIN)
        self.document_key = self.baseline["source"]["document_key"]

    def test_import_merges_full_hierarchy_with_bounded_calculation(self) -> None:
        self.assertEqual(self.baseline["counts"]["tasks"], 5)
        self.assertEqual(self.baseline["counts"]["summary_tasks"], 2)
        self.assertEqual(self.baseline["counts"]["supported_activities"], 3)
        self.assertEqual(
            self.baseline["limits"]["maximum_duration_seconds"],
            365 * 24 * 60 * 60,
        )
        self.assertEqual(
            [row["id"] for row in self.baseline["tasks"]],
            ["task:0", "task:1", "task:2", "task:3", "task:4"],
        )

        summaries = [
            row for row in self.baseline["tasks"] if row["kind"] == "summary"
        ]
        self.assertEqual(len(summaries), 2)
        self.assertTrue(all(row["calculated_start"] is None for row in summaries))
        self.assertTrue(
            all(row["reason_codes"] == ["SUMMARY_TASK"] for row in summaries)
        )

        activities = [
            row for row in self.baseline["tasks"] if row["kind"] == "activity"
        ]
        self.assertTrue(all(row["supported"] for row in activities))
        self.assertTrue(all(row["calculated_start"] for row in activities))
        self.assertTrue(all(row["primary_reason"] is None for row in activities))
        self.assertEqual(activities[0]["wbs"], "MECH.ISO")
        self.assertEqual(activities[0]["outline_number"], "1.1")
        self.assertTrue(activities[0]["has_supported_successor"])
        self.assertFalse(activities[-1]["editable"])

    def test_duration_change_moves_edited_and_downstream_activities(self) -> None:
        scenario = self.workspace.recalculate_duration(
            "task:2", 8 * 60 * 60, document_key=self.document_key
        )
        by_id = {row["id"]: row for row in scenario["tasks"]}

        self.assertTrue(scenario["scenario"]["changed"])
        self.assertEqual(scenario["scenario"]["moved_activity_count"], 3)
        self.assertEqual(
            scenario["scenario"]["downstream_moved_activity_count"], 2
        )
        self.assertEqual(by_id["task:2"]["impact"], "edited")
        self.assertEqual(by_id["task:2"]["imported_duration_seconds"], 14400)
        self.assertEqual(by_id["task:2"]["scenario_duration_seconds"], 28800)
        self.assertEqual(
            by_id["task:2"]["calculated_finish"], "2026-01-05T17:00:00"
        )
        self.assertEqual(by_id["task:3"]["impact"], "downstream")
        self.assertEqual(
            by_id["task:3"]["calculated_start"], "2026-01-06T08:00:00"
        )
        self.assertEqual(
            by_id["task:4"]["calculated_finish"], "2026-01-06T12:00:00"
        )
        self.assertNotEqual(
            scenario["scenario"]["current_calculation_sha256"],
            scenario["scenario"]["base_calculation_sha256"],
        )

    def test_reset_restores_import_time_calculation_without_closing_schedule(
        self,
    ) -> None:
        self.workspace.recalculate_duration(
            "task:2", 28800, document_key=self.document_key
        )
        reset = self.workspace.reset()
        self.assertTrue(reset["loaded"])
        self.assertFalse(reset["scenario"]["changed"])
        self.assertEqual(reset["scenario"]["moved_activity_count"], 0)
        self.assertEqual(reset["scenario"]["duration_overrides"], [])
        self.assertEqual(
            reset["scenario"]["current_calculation_sha256"],
            reset["scenario"]["base_calculation_sha256"],
        )
        self.assertEqual(
            {row["id"]: row for row in reset["tasks"]}["task:2"][
                "calculated_finish"
            ],
            "2026-01-05T12:00:00",
        )

    def test_second_level_duration_is_preserved(self) -> None:
        scenario = self.workspace.recalculate_duration(
            "task:2",
            14_401,
            document_key=self.document_key,
            revision=0,
        )
        row = {item["id"]: item for item in scenario["tasks"]}["task:2"]
        self.assertEqual(row["scenario_duration_seconds"], 14_401)
        self.assertEqual(
            scenario["scenario"]["duration_overrides"][0]["duration_seconds"],
            14_401,
        )

    def test_scenario_cannot_cross_an_ignored_calendar_exception(self) -> None:
        document = import_mspdi(CHAIN)
        document["calendars"][0]["exceptions"].append(
            _calendar_exception(
                "calendar-exception:1:scenario-boundary",
                "2026-01-06T00:00:00",
                "2026-01-06T23:59:59",
            )
        )
        workspace = ScheduleWorkspace()
        baseline = workspace.load_document(document)
        self.assertEqual(baseline["counts"]["supported_activities"], 3)

        with self.assertRaisesRegex(InvalidDurationError, "calendar exception"):
            workspace.recalculate_duration(
                "task:2",
                12 * 60 * 60,
                document_key=baseline["source"]["document_key"],
                revision=0,
            )
        self.assertFalse(workspace.snapshot()["scenario"]["changed"])

    def test_scenario_horizon_catches_working_exception_between_tasks(
        self,
    ) -> None:
        document = import_mspdi(CHAIN)
        document["calendars"][0]["exceptions"].append(
            _calendar_exception(
                "calendar-exception:1:working-saturday",
                "2026-01-10T08:00:00",
                "2026-01-10T17:00:00",
                working=True,
            )
        )
        workspace = ScheduleWorkspace()
        baseline = workspace.load_document(document)
        self.assertTrue(baseline["calculation"]["available"])

        with self.assertRaisesRegex(InvalidDurationError, "calendar exception"):
            workspace.recalculate_duration(
                "task:2",
                40 * 60 * 60,
                document_key=baseline["source"]["document_key"],
                revision=0,
            )

    def test_scenario_horizon_includes_negative_lag_candidate(self) -> None:
        document = import_mspdi(CHAIN)
        relationship = document["relationships"][0]
        relationship["lag_tenths_minutes"] = -14_400
        relationship["lag_seconds"] = -86_400
        relationship["lag_format_source"] = 8
        document["calendars"][0]["exceptions"].append(
            _calendar_exception(
                "calendar-exception:1:working-sunday",
                "2026-01-04T08:00:00",
                "2026-01-04T10:00:00",
                working=True,
            )
        )
        workspace = ScheduleWorkspace()
        baseline = workspace.load_document(document)
        self.assertTrue(baseline["calculation"]["available"])

        with self.assertRaisesRegex(InvalidDurationError, "calendar exception"):
            workspace.recalculate_duration(
                "task:2",
                60 * 60,
                document_key=baseline["source"]["document_key"],
                revision=0,
            )

    def test_base_calculation_is_withheld_if_it_crosses_ignored_exception(
        self,
    ) -> None:
        document = import_mspdi(CHAIN)
        by_id = {item["id"]: item for item in document["activities"]}
        for activity_id in ("task:2", "task:3"):
            by_id[activity_id]["start"] = "2026-01-05T08:00:00"
            by_id[activity_id]["finish"] = "2026-01-05T17:00:00"
            by_id[activity_id]["duration"] = _duration(28_800, "PT8H0M0S")
            by_id[activity_id]["remaining_duration_source"] = _duration(
                28_800, "PT8H0M0S"
            )
        document["calendars"][0]["exceptions"].append(
            _calendar_exception(
                "calendar-exception:1:base-boundary",
                "2026-01-06T00:00:00",
                "2026-01-06T23:59:59",
            )
        )

        snapshot = ScheduleWorkspace().load_document(document)
        self.assertFalse(snapshot["calculation"]["available"])
        self.assertEqual(snapshot["counts"]["supported_activities"], 0)
        self.assertIn("calendar exception", snapshot["calculation"]["error"])

    def test_all_identical_resource_calendar_lineages_are_guarded(self) -> None:
        document = import_mspdi(CHAIN)
        task = next(item for item in document["activities"] if item["id"] == "task:2")
        for extension_ref in task["extension_refs"]:
            extension = next(
                item
                for item in document["vendor_extensions"]
                if item["id"] == extension_ref
            )
            if extension["payload"].get("name") == "IgnoreResourceCalendar":
                extension["payload"]["text"] = "0"

        first_calendar = deepcopy(document["calendars"][0])
        first_calendar["id"] = "calendar:2"
        second_calendar = deepcopy(document["calendars"][0])
        second_calendar["id"] = "calendar:3"
        second_calendar["exceptions"].append(
            _calendar_exception(
                "calendar-exception:3:resource-boundary",
                "2026-01-06T00:00:00",
                "2026-01-06T23:59:59",
            )
        )
        document["calendars"].extend([first_calendar, second_calendar])
        document["resources"] = [
            {
                "id": "resource:1",
                "calendar_ref": "calendar:2",
                "inactive_source": False,
            },
            {
                "id": "resource:2",
                "calendar_ref": "calendar:3",
                "inactive_source": False,
            },
        ]
        document["assignments"] = [
            {
                "id": f"assignment:{index}",
                "source_order": index,
                "task_ref": "task:2",
                "resource_ref": f"resource:{index}",
                "units_source": 1,
                "work_source": _duration(14_400, "PT4H0M0S"),
                "actual_work_source": _duration(0, "PT0H0M0S"),
                "remaining_work_source": _duration(14_400, "PT4H0M0S"),
                "percent_work_complete_source": 0,
                "work_contour_source": 0,
                "extension_refs": [],
            }
            for index in (1, 2)
        ]

        workspace = ScheduleWorkspace()
        baseline = workspace.load_document(document)
        self.assertTrue(
            {row["id"]: row for row in baseline["tasks"]}["task:2"]["editable"]
        )
        with self.assertRaisesRegex(InvalidDurationError, "calendar exception"):
            workspace.recalculate_duration(
                "task:2",
                12 * 60 * 60,
                document_key=baseline["source"]["document_key"],
                revision=0,
            )

    def test_milestone_only_calendar_exception_does_not_block_scenario(
        self,
    ) -> None:
        document = import_mspdi(CHAIN)
        milestone = next(
            item for item in document["activities"] if item["id"] == "task:4"
        )
        milestone_calendar = deepcopy(document["calendars"][0])
        milestone_calendar["id"] = "calendar:2"
        milestone_calendar["exceptions"].append(
            _calendar_exception(
                "calendar-exception:2:milestone-only",
                "2026-01-06T00:00:00",
                "2026-01-06T23:59:59",
            )
        )
        document["calendars"].append(milestone_calendar)
        milestone["calendar_ref"] = "calendar:2"

        workspace = ScheduleWorkspace()
        baseline = workspace.load_document(document)
        scenario = workspace.recalculate_duration(
            "task:2",
            8 * 60 * 60,
            document_key=baseline["source"]["document_key"],
            revision=0,
        )
        milestone_row = {row["id"]: row for row in scenario["tasks"]}["task:4"]
        self.assertEqual(milestone_row["calculated_start"], "2026-01-06T12:00:00")

    def test_unrelated_calendar_exception_does_not_block_scenario(self) -> None:
        document = import_mspdi(CHAIN)
        document["relationships"] = []

        unaffected_calendar = deepcopy(document["calendars"][0])
        unaffected_calendar["id"] = "calendar:2"
        document["calendars"][0]["exceptions"].append(
            _calendar_exception(
                "calendar-exception:1:unrelated",
                "2026-01-06T00:00:00",
                "2026-01-06T23:59:59",
            )
        )
        document["calendars"].append(unaffected_calendar)
        task = next(
            item for item in document["activities"] if item["id"] == "task:3"
        )
        task["calendar_ref"] = "calendar:2"

        workspace = ScheduleWorkspace()
        baseline = workspace.load_document(document)
        scenario = workspace.recalculate_duration(
            "task:3",
            12 * 60 * 60,
            document_key=baseline["source"]["document_key"],
            revision=0,
        )

        task_row = {row["id"]: row for row in scenario["tasks"]}["task:3"]
        self.assertEqual(task_row["calculated_finish"], "2026-01-06T12:00:00")

    def test_invalid_project_start_falls_back_to_imported_only_view(self) -> None:
        document = import_mspdi(CHAIN)
        document["project"]["start"] = None
        workspace = ScheduleWorkspace()
        snapshot = workspace.load_document(document)

        self.assertTrue(snapshot["loaded"])
        self.assertFalse(snapshot["calculation"]["available"])
        self.assertEqual(snapshot["counts"]["supported_activities"], 0)
        self.assertTrue(
            all(row["calculated_start"] is None for row in snapshot["tasks"])
        )

    def test_edit_boundary_rejects_stale_unsupported_and_invalid_requests(self) -> None:
        with self.assertRaisesRegex(
            ActivityNotEditableError, "different imported schedule"
        ):
            self.workspace.recalculate_duration(
                "task:2", 28800, document_key="sha256:stale"
            )
        with self.assertRaisesRegex(ActivityNotEditableError, "Milestone"):
            self.workspace.recalculate_duration(
                "task:4", 60, document_key=self.document_key
            )
        for invalid in (True, 0, -1, 365 * 24 * 60 * 60 + 1):
            with self.subTest(invalid=invalid):
                with self.assertRaises(InvalidDurationError):
                    self.workspace.recalculate_duration(
                        "task:2", invalid, document_key=self.document_key
                    )

        unsupported = ScheduleWorkspace()
        unsupported_snapshot = unsupported.load_mspdi(
            FIXTURES / "synthetic-basic.mspdi.xml"
        )
        for row in unsupported_snapshot["tasks"]:
            if row["reason_codes"]:
                self.assertIn(row["primary_reason"], row["reason_codes"])
        with self.assertRaisesRegex(ActivityNotEditableError, "admitted"):
            unsupported.recalculate_duration("task:2", 28800)

        with self.assertRaisesRegex(ActivityNotEditableError, "another workspace tab"):
            self.workspace.recalculate_duration(
                "task:2",
                28800,
                document_key=self.document_key,
                revision=9,
            )

    def test_export_is_current_inspectable_json_state(self) -> None:
        self.workspace.recalculate_duration(
            "task:2", 28800, document_key=self.document_key
        )
        export = self.workspace.export_state()
        round_trip = json.loads(json.dumps(export))
        self.assertEqual(
            round_trip["export_type"],
            "prototype-0-local-schedule-workspace-state",
        )
        self.assertEqual(round_trip["source"]["document_key"], self.document_key)
        self.assertEqual(
            round_trip["scenario"]["duration_overrides"],
            [
                {
                    "activity_id": "task:2",
                    "imported_duration_seconds": 14400,
                    "duration_seconds": 28800,
                }
            ],
        )
        self.assertEqual(round_trip["native_project_validation"], "not_executed")

    def test_byte_import_discards_paths_from_display_name(self) -> None:
        workspace = ScheduleWorkspace()
        snapshot = workspace.load_mspdi_bytes(
            CHAIN.read_bytes(), display_name=r"C:\private\shutdown.xml"
        )
        self.assertEqual(snapshot["display_name"], "shutdown.xml")

    def test_reset_and_export_require_an_import(self) -> None:
        empty = ScheduleWorkspace()
        with self.assertRaises(WorkspaceNotLoadedError):
            empty.reset()
        with self.assertRaises(WorkspaceNotLoadedError):
            empty.export_state()

    def test_failed_recalculation_does_not_partially_change_scenario(self) -> None:
        with patch(
            "sto_scheduler_core.workspace.calculate_forward_schedule",
            side_effect=CalculationProfileError("synthetic calculation failure"),
        ):
            with self.assertRaisesRegex(
                CalculationProfileError, "synthetic calculation failure"
            ):
                self.workspace.recalculate_duration(
                    "task:2", 28800, document_key=self.document_key
                )

        snapshot = self.workspace.snapshot()
        self.assertFalse(snapshot["scenario"]["changed"])
        self.assertEqual(snapshot["scenario"]["revision"], 0)
        self.assertEqual(snapshot["scenario"]["duration_overrides"], [])
        self.assertEqual(
            snapshot["scenario"]["current_calculation_sha256"],
            snapshot["scenario"]["base_calculation_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
