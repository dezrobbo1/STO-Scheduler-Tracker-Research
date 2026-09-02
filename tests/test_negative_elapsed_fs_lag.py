from __future__ import annotations

import unittest

from sto.legacy.calculation_profile import (
    CalculationProfileError,
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
    compare_source_coordinates,
)

from calculation_fixture import _activity, _calendar, _document, _relationship


ELAPSED_DAY_TENTHS = 24 * 60 * 10


class NegativeElapsedFsLagTests(unittest.TestCase):
    def test_negative_elapsed_lead_lands_in_working_time(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-08T12:00:00", duration_seconds=100800),
                _activity(2, start="2026-01-07T12:00:00", finish="2026-01-07T16:00:00", duration_seconds=14400),
            ],
            relationships=[_relationship(1, 1, 2, lag=-ELAPSED_DAY_TENTHS, lag_format=8)],
        )
        profile = build_calculation_profile(document)
        self.assertEqual(profile["counts"]["eligible_activities"], 2)
        self.assertEqual(profile["counts"]["eligible_relationships"], 1)
        projection = build_engine_projection(document, profile)
        self.assertEqual(projection["relationships"][0]["lag_basis"], "elapsed")
        comparison = compare_source_coordinates(document, calculate_forward_schedule(projection))
        self.assertEqual(comparison["counts"]["coordinate_differences"], 0)

    def test_negative_elapsed_lead_normalizes_successor_to_next_working_time(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-08T20:00:00", duration_seconds=100800),
                _activity(2, start="2026-01-08T08:00:00", finish="2026-01-08T12:00:00", duration_seconds=14400),
            ],
            relationships=[_relationship(1, 1, 2, lag=-ELAPSED_DAY_TENTHS, lag_format=8)],
        )
        comparison = compare_source_coordinates(
            document,
            calculate_forward_schedule(build_engine_projection(document, build_calculation_profile(document))),
        )
        self.assertEqual(comparison["counts"]["coordinate_differences"], 0)

    def test_negative_elapsed_lead_may_place_successor_before_project_start(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400),
                _activity(2, start="2026-01-04T12:00:00", finish="2026-01-04T16:00:00", duration_seconds=14400),
            ],
            relationships=[_relationship(1, 1, 2, lag=-ELAPSED_DAY_TENTHS, lag_format=8)],
        )
        comparison = compare_source_coordinates(
            document,
            calculate_forward_schedule(build_engine_projection(document, build_calculation_profile(document))),
        )
        self.assertEqual(comparison["counts"]["coordinate_differences"], 0)

    def test_multiple_predecessors_choose_latest_lag_adjusted_driver(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-08T12:00:00", duration_seconds=100800),
                _activity(2, start="2026-01-05T08:00:00", finish="2026-01-07T14:00:00", duration_seconds=79200),
                _activity(3, start="2026-01-07T14:00:00", finish="2026-01-08T10:00:00", duration_seconds=14400),
            ],
            relationships=[
                _relationship(1, 1, 3, lag=-ELAPSED_DAY_TENTHS, lag_format=8),
                _relationship(2, 2, 3),
            ],
        )
        comparison = compare_source_coordinates(
            document,
            calculate_forward_schedule(build_engine_projection(document, build_calculation_profile(document))),
        )
        self.assertEqual(comparison["counts"]["coordinate_differences"], 0)

    def test_positive_elapsed_lag_remains_excluded(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400),
                _activity(2, start="2026-01-06T08:00:00", finish="2026-01-06T12:00:00", duration_seconds=14400),
            ],
            relationships=[_relationship(1, 1, 2, lag=ELAPSED_DAY_TENTHS, lag_format=8)],
        )
        record = {item["activity_id"]: item for item in build_calculation_profile(document)["activities"]}["task:2"]
        self.assertIn("RELATIONSHIP_LAG_UNSUPPORTED", record["reason_codes"])

    def test_negative_non_elapsed_lag_remains_excluded(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400),
                _activity(2, start="2026-01-05T10:00:00", finish="2026-01-05T14:00:00", duration_seconds=14400),
            ],
            relationships=[_relationship(1, 1, 2, lag=-600, lag_format=7)],
        )
        record = {item["activity_id"]: item for item in build_calculation_profile(document)["activities"]}["task:2"]
        self.assertIn("RELATIONSHIP_LAG_UNSUPPORTED", record["reason_codes"])

    def test_negative_elapsed_lag_with_inconsistent_seconds_remains_excluded(self) -> None:
        relationship = _relationship(
            1, 1, 2, lag=-ELAPSED_DAY_TENTHS, lag_format=8
        )
        relationship["lag_seconds"] = -1
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400),
                _activity(2, start="2026-01-04T12:00:00", finish="2026-01-04T16:00:00", duration_seconds=14400),
            ],
            relationships=[relationship],
        )
        record = {item["activity_id"]: item for item in build_calculation_profile(document)["activities"]}["task:2"]
        self.assertIn("RELATIONSHIP_LAG_UNSUPPORTED", record["reason_codes"])

    def test_calendar_exception_at_pre_project_lead_candidate_fails_closed(self) -> None:
        exception = {
            "id": "exception:lead-candidate",
            "from": "2026-01-04T00:00:00",
            "to": "2026-01-04T23:59:00",
        }
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400),
                _activity(2, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400),
            ],
            relationships=[_relationship(1, 1, 2, lag=-ELAPSED_DAY_TENTHS, lag_format=8)],
            calendars=[
                _calendar(
                    1,
                    [("08:00:00", "16:00:00")],
                    exceptions=[exception],
                )
            ],
        )
        record = {item["activity_id"]: item for item in build_calculation_profile(document)["activities"]}["task:2"]
        self.assertIn("TASK_CALENDAR_UNRESOLVED", record["reason_codes"])

    def test_negative_elapsed_lag_into_milestone_remains_excluded(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-08T12:00:00", duration_seconds=100800),
                _activity(2, start="2026-01-07T12:00:00", finish="2026-01-07T12:00:00", duration_seconds=0, milestone=True),
            ],
            relationships=[_relationship(1, 1, 2, lag=-ELAPSED_DAY_TENTHS, lag_format=8)],
        )
        record = {item["activity_id"]: item for item in build_calculation_profile(document)["activities"]}["task:2"]
        self.assertIn("RELATIONSHIP_LAG_UNSUPPORTED", record["reason_codes"])

    def test_engine_rejects_tampered_negative_lag_into_milestone(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400),
                _activity(2, start="2026-01-05T12:00:00", finish="2026-01-05T12:00:00", duration_seconds=0, milestone=True),
            ],
            relationships=[_relationship(1, 1, 2)],
        )
        projection = build_engine_projection(document, build_calculation_profile(document))
        projection["relationships"][0]["lag_seconds"] = -86400
        projection["relationships"][0]["lag_basis"] = "elapsed"
        with self.assertRaisesRegex(CalculationProfileError, "milestone"):
            calculate_forward_schedule(projection)


if __name__ == "__main__":
    unittest.main()
