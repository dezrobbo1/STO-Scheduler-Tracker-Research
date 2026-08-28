from __future__ import annotations

import json
import unittest

from sto_scheduler_core.calculation_eligibility import (
    ELIGIBILITY_PROFILE,
    classify_calculation_eligibility,
    sanitized_eligibility_evidence,
)


def _duration(seconds: int) -> dict[str, object]:
    return {"raw": f"PT{seconds}S", "seconds": seconds, "status": "parsed"}


def _activity(activity_id: str, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": activity_id,
        "active": True,
        "manual": False,
        "is_null_source": False,
        "start": "2026-01-01T08:00:00",
        "finish": "2026-01-01T12:00:00",
        "duration": _duration(14_400),
        "milestone": False,
        "percent_complete_source": 0,
        "percent_work_complete_source": 0,
        "physical_percent_complete_source": 0,
        "actual_start_source": None,
        "actual_finish_source": None,
        "actual_duration_source": _duration(0),
        "actual_work_source": _duration(0),
        "remaining_duration_source": _duration(14_400),
        "deadline_source": None,
        "constraint_type_source": 0,
        "constraint_date_source": None,
        "calendar_ref": "calendar:1",
    }
    record.update(overrides)
    return record


def _relationship(
    relationship_id: str,
    predecessor: str,
    successor: str,
    **overrides: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "id": relationship_id,
        "predecessor_ref": predecessor,
        "successor_ref": successor,
        "type": "FS",
        "lag_tenths_minutes": 0,
        "cross_project": False,
    }
    record.update(overrides)
    return record


def _document(
    activities: list[dict[str, object]],
    relationships: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "project": {"calendar_ref": "calendar:1"},
        "activities": activities,
        "relationships": relationships or [],
        "calendars": [
            {
                "id": "calendar:1",
                "base_calendar_ref": None,
                "week_days": [
                    {
                        "day_type": 2,
                        "working_times": [{"from": "08:00:00", "to": "12:00:00"}],
                    }
                ],
                "exceptions": [],
            }
        ],
        "resources": [],
        "assignments": [],
    }


class CalculationEligibilityTests(unittest.TestCase):
    def test_supported_closed_network_is_eligible(self) -> None:
        result = classify_calculation_eligibility(
            _document(
                [_activity("task:1"), _activity("task:2")],
                [_relationship("relationship:1", "task:1", "task:2")],
            )
        )
        self.assertEqual(result["profile"], ELIGIBILITY_PROFILE)
        self.assertEqual(result["eligible_activity_ids"], ["task:1", "task:2"])
        self.assertEqual(result["eligible_relationship_ids"], ["relationship:1"])
        self.assertEqual(result["counts"]["excluded_activities"], 0)

    def test_local_unsupported_semantics_fail_closed(self) -> None:
        document = _document(
            [
                _activity("task:manual", manual=True),
                _activity("task:actual", actual_start_source="2026-01-01T08:00:00"),
                _activity("task:deadline", deadline_source="2026-01-02T00:00:00"),
                _activity("task:constraint", constraint_type_source=2),
                _activity("task:duration", duration={"raw": "not-parsed", "seconds": None}),
            ]
        )
        result = classify_calculation_eligibility(document)
        reasons = result["excluded_activity_reasons"]
        self.assertIn("manual_scheduling", reasons["task:manual"])
        self.assertIn("actual_state", reasons["task:actual"])
        self.assertIn("deadline", reasons["task:deadline"])
        self.assertIn("unsupported_constraint", reasons["task:constraint"])
        self.assertIn("unparsed_duration", reasons["task:duration"])
        self.assertEqual(result["counts"]["eligible_activities"], 0)

    def test_calendar_exception_and_resource_calendar_interaction_fail_closed(self) -> None:
        document = _document([_activity("task:1"), _activity("task:2")])
        document["calendars"][0]["exceptions"] = [{"from": "2026-01-01", "to": "2026-01-01"}]
        document["calendars"].append(
            {
                "id": "calendar:2",
                "base_calendar_ref": None,
                "week_days": [{"day_type": 2, "working_times": [{"from": "09:00:00", "to": "13:00:00"}]}],
                "exceptions": [],
            }
        )
        document["resources"] = [{"id": "resource:1", "calendar_ref": "calendar:2"}]
        document["assignments"] = [
            {"id": "assignment:1", "task_ref": "task:2", "resource_ref": "resource:1"}
        ]
        result = classify_calculation_eligibility(document)
        reasons = result["excluded_activity_reasons"]
        self.assertIn("calendar_exceptions", reasons["task:1"])
        self.assertIn("calendar_exceptions", reasons["task:2"])
        self.assertIn("resource_calendar_interaction", reasons["task:2"])

    def test_network_closure_removes_supported_neighbour_of_ineligible_task(self) -> None:
        result = classify_calculation_eligibility(
            _document(
                [_activity("task:1"), _activity("task:2", manual=True), _activity("task:3")],
                [
                    _relationship("relationship:1", "task:1", "task:2"),
                    _relationship("relationship:2", "task:2", "task:3"),
                ],
            )
        )
        self.assertEqual(result["eligible_activity_ids"], [])
        reasons = result["excluded_activity_reasons"]
        self.assertIn("network_has_ineligible_successor", reasons["task:1"])
        self.assertIn("manual_scheduling", reasons["task:2"])
        self.assertIn("network_has_ineligible_predecessor", reasons["task:3"])

    def test_unsupported_relationship_removes_both_endpoints(self) -> None:
        result = classify_calculation_eligibility(
            _document(
                [_activity("task:1"), _activity("task:2")],
                [_relationship("relationship:1", "task:1", "task:2", type="UNKNOWN")],
            )
        )
        self.assertEqual(result["eligible_activity_ids"], [])
        self.assertEqual(
            result["unsupported_relationship_reasons"]["relationship:1"],
            ["unsupported_relationship_type"],
        )
        for activity_id in ("task:1", "task:2"):
            self.assertIn(
                "unsupported_adjacent_relationship",
                result["excluded_activity_reasons"][activity_id],
            )

    def test_sanitized_evidence_contains_hashes_not_task_ids(self) -> None:
        result = classify_calculation_eligibility(
            _document(
                [_activity("task:sensitive-a"), _activity("task:sensitive-b", manual=True)]
            )
        )
        evidence = sanitized_eligibility_evidence(result)
        serialized = json.dumps(evidence, sort_keys=True)
        self.assertNotIn("task:sensitive-a", serialized)
        self.assertNotIn("task:sensitive-b", serialized)
        self.assertEqual(len(evidence["set_fingerprints"]["eligible_activity_ids_sha256"]), 64)
        self.assertIn("manual_scheduling", evidence["set_fingerprints"]["excluded_activity_ids_by_reason_sha256"])


if __name__ == "__main__":
    unittest.main()
