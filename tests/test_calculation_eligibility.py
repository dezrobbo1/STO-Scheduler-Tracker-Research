from __future__ import annotations

import json
import unittest

from sto_scheduler_core.calculation_profile import (
    CalculationProfileError,
    PROFILE_VERSION,
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
    compare_source_coordinates,
    sanitized_profile_evidence,
)

from calculation_fixture import _activity, _calendar, _document, _duration, _relationship


class CalculationProfileTests(unittest.TestCase):
    def test_ineligible_predecessor_closes_successor(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400, active=False),
                _activity(2, start="2026-01-05T12:00:00", finish="2026-01-05T16:00:00", duration_seconds=14400),
            ],
            relationships=[_relationship(1, 1, 2)],
        )
        profile = build_calculation_profile(document)
        by_id = {item["activity_id"]: item for item in profile["activities"]}
        self.assertIn("ACTIVITY_INACTIVE", by_id["task:1"]["reason_codes"])
        self.assertIn("INELIGIBLE_PREDECESSOR", by_id["task:2"]["reason_codes"])
        self.assertEqual(profile["counts"]["eligible_activities"], 0)

    def test_nonzero_lag_excludes_successor_and_closes_network(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T10:00:00", duration_seconds=7200),
                _activity(2, start="2026-01-05T10:00:00", finish="2026-01-05T12:00:00", duration_seconds=7200),
                _activity(3, start="2026-01-05T12:00:00", finish="2026-01-05T14:00:00", duration_seconds=7200),
            ],
            relationships=[_relationship(1, 1, 2, lag=-600), _relationship(2, 2, 3)],
        )
        profile = build_calculation_profile(document)
        by_id = {item["activity_id"]: item for item in profile["activities"]}
        self.assertIn("RELATIONSHIP_LAG_UNSUPPORTED", by_id["task:2"]["reason_codes"])
        self.assertIn("INELIGIBLE_PREDECESSOR", by_id["task:3"]["reason_codes"])
        self.assertEqual(profile["counts"]["eligible_activities"], 1)

    def test_resource_calendar_is_effective_when_task_calendar_is_not_explicit(self) -> None:
        resource = {
            "id": "resource:1",
            "source_order": 1,
            "external_references": [],
            "name": "Sensitive resource",
            "calendar_ref": "calendar:2",
        }
        assignment = {
            "id": "assignment:1",
            "source_order": 1,
            "task_ref": "task:1",
            "resource_ref": "resource:1",
            "units_source": 1,
            "work_source": _duration(14400),
            "actual_work_source": _duration(0),
            "remaining_work_source": _duration(14400),
            "percent_work_complete_source": 0,
            "work_contour_source": 0,
            "extension_refs": [],
        }
        document = _document(
            [
                _activity(1, start="2026-01-05T18:00:00", finish="2026-01-05T22:00:00", duration_seconds=14400),
            ],
            calendars=[
                _calendar(1, [("08:00:00", "16:00:00")]),
                _calendar(2, [("18:00:00", "00:00:00")]),
            ],
            resources=[resource],
            assignments=[assignment],
        )
        profile = build_calculation_profile(document)
        self.assertEqual(profile["counts"]["eligible_activities"], 1)
        comparison = compare_source_coordinates(
            document, calculate_forward_schedule(build_engine_projection(document, profile))
        )
        self.assertEqual(comparison["counts"]["coordinate_differences"], 0)

    def test_multiple_resource_patterns_fail_closed(self) -> None:
        resources = [
            {"id": "resource:1", "source_order": 1, "external_references": [], "name": "R1", "calendar_ref": "calendar:1"},
            {"id": "resource:2", "source_order": 2, "external_references": [], "name": "R2", "calendar_ref": "calendar:2"},
        ]
        assignments = [
            {"id": "assignment:1", "source_order": 1, "task_ref": "task:1", "resource_ref": "resource:1", "units_source": 1, "work_source": _duration(14400), "actual_work_source": _duration(0), "remaining_work_source": _duration(14400), "percent_work_complete_source": 0, "work_contour_source": 0, "extension_refs": []},
            {"id": "assignment:2", "source_order": 2, "task_ref": "task:1", "resource_ref": "resource:2", "units_source": 1, "work_source": _duration(14400), "actual_work_source": _duration(0), "remaining_work_source": _duration(14400), "percent_work_complete_source": 0, "work_contour_source": 0, "extension_refs": []},
        ]
        document = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400)],
            calendars=[_calendar(1, [("08:00:00", "16:00:00")]), _calendar(2, [("18:00:00", "00:00:00")])],
            resources=resources,
            assignments=assignments,
        )
        profile = build_calculation_profile(document)
        record = profile["activities"][0]
        self.assertFalse(record["eligible"])
        self.assertIn("MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED", record["reason_codes"])

    def test_nonoverlapping_exception_is_allowed_but_overlapping_exception_is_not(self) -> None:
        outside = {
            "id": "exception:outside",
            "from": "2025-12-25T00:00:00",
            "to": "2025-12-25T23:59:00",
        }
        inside = {
            "id": "exception:inside",
            "from": "2026-01-06T00:00:00",
            "to": "2026-01-06T23:59:00",
        }
        allowed = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400)],
            calendars=[_calendar(1, [("08:00:00", "16:00:00")], exceptions=[outside])],
        )
        rejected = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400)],
            calendars=[_calendar(1, [("08:00:00", "16:00:00")], exceptions=[inside])],
        )
        self.assertEqual(build_calculation_profile(allowed)["counts"]["eligible_activities"], 1)
        record = build_calculation_profile(rejected)["activities"][0]
        self.assertIn("TASK_CALENDAR_UNRESOLVED", record["reason_codes"])

    def test_work_units_mismatch_and_duration_format_fail_closed(self) -> None:
        resource = {
            "id": "resource:1",
            "source_order": 1,
            "external_references": [],
            "name": "R1",
            "calendar_ref": "calendar:1",
            "inactive_source": False,
        }
        assignment = {
            "id": "assignment:1",
            "source_order": 1,
            "task_ref": "task:1",
            "resource_ref": "resource:1",
            "units_source": 1,
            "work_source": _duration(7200),
            "actual_work_source": _duration(0),
            "remaining_work_source": _duration(7200),
            "percent_work_complete_source": 0,
            "work_contour_source": 0,
            "extension_refs": [],
        }
        document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                    duration_format="8",
                )
            ],
            resources=[resource],
            assignments=[assignment],
        )
        record = build_calculation_profile(document)["activities"][0]
        self.assertIn("DURATION_FORMAT_UNSUPPORTED", record["reason_codes"])
        self.assertIn("WORK_UNITS_INCONSISTENT", record["reason_codes"])

    def test_cross_midnight_interval_fails_closed(self) -> None:
        document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T18:00:00",
                    finish="2026-01-06T02:00:00",
                    duration_seconds=28800,
                )
            ],
            calendars=[_calendar(1, [("18:00:00", "06:00:00")])],
        )
        record = build_calculation_profile(document)["activities"][0]
        self.assertIn("TASK_CALENDAR_UNRESOLVED", record["reason_codes"])

    def test_special_calendar_day_inside_horizon_fails_closed(self) -> None:
        calendar = _calendar(1, [("08:00:00", "16:00:00")])
        calendar["week_days"].append(
            {
                "day_type": 0,
                "working": False,
                "working_times": [],
                "extensions": [
                    {
                        "name": "TimePeriod",
                        "children": [
                            {"name": "FromDate", "text": "2026-01-06T00:00:00"},
                            {"name": "ToDate", "text": "2026-01-06T23:59:00"},
                        ],
                    }
                ],
            }
        )
        document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                )
            ],
            calendars=[calendar],
        )
        record = build_calculation_profile(document)["activities"][0]
        self.assertIn("TASK_CALENDAR_UNRESOLVED", record["reason_codes"])


if __name__ == "__main__":
    unittest.main()
