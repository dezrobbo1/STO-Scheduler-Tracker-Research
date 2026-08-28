from __future__ import annotations

import unittest

from sto_scheduler_core.calculation_profile import build_calculation_profile

from calculation_fixture import _activity, _calendar, _document, _duration


class CalculationReviewCorrectionTests(unittest.TestCase):
    def test_unparsed_actual_duration_and_assignment_work_fail_closed(self) -> None:
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
            "work_source": _duration(14400),
            "actual_work_source": {
                "raw": "UNPARSEABLE-ACTUAL-WORK",
                "seconds": None,
                "parse_status": "unsupported",
            },
            "remaining_work_source": _duration(14400),
            "percent_work_complete_source": 0,
            "work_contour_source": 0,
            "extension_refs": [],
        }
        activity = _activity(
            1,
            start="2026-01-05T08:00:00",
            finish="2026-01-05T12:00:00",
            duration_seconds=14400,
        )
        activity[0]["actual_duration_source"] = {
            "raw": "UNPARSEABLE-ACTUAL-DURATION",
            "seconds": None,
            "parse_status": "unsupported",
        }
        document = _document(
            [activity],
            resources=[resource],
            assignments=[assignment],
        )

        record = build_calculation_profile(document)["activities"][0]
        self.assertFalse(record["eligible"])
        self.assertIn("ACTUAL_STATE_PRESENT", record["reason_codes"])
        self.assertIn("ASSIGNMENT_PROGRESS_STATE_PRESENT", record["reason_codes"])

    def test_equal_non_midnight_calendar_endpoints_fail_closed(self) -> None:
        document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                )
            ],
            calendars=[_calendar(1, [("08:00:00", "08:00:00")])],
        )

        record = build_calculation_profile(document)["activities"][0]
        self.assertFalse(record["eligible"])
        self.assertIn("TASK_CALENDAR_UNRESOLVED", record["reason_codes"])


if __name__ == "__main__":
    unittest.main()
