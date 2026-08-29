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
    def test_simple_fs_network_projects_and_compares_exactly(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400),
                _activity(2, start="2026-01-05T12:00:00", finish="2026-01-05T16:00:00", duration_seconds=14400),
            ],
            relationships=[_relationship(1, 1, 2)],
        )
        profile = build_calculation_profile(document)
        projection = build_engine_projection(document, profile)
        calculation = calculate_forward_schedule(projection)
        comparison = compare_source_coordinates(document, calculation)

        self.assertEqual(profile["profile"], PROFILE_VERSION)
        self.assertEqual(profile["counts"]["eligible_activities"], 2)
        self.assertEqual(profile["counts"]["eligible_relationships"], 1)
        self.assertEqual(comparison["counts"]["exact_coordinate_matches"], 2)
        self.assertEqual(comparison["counts"]["coordinate_differences"], 0)
        self.assertEqual(comparison["source"], calculation["source"])
        self.assertFalse(any("name" in item for item in projection["activities"]))

    def test_milestone_keeps_predecessor_time_without_calendar_snap(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T13:00:00", finish="2026-01-05T17:00:00", duration_seconds=14400, calendar_ref="calendar:2", ignore_resource_calendar="1"),
                _activity(2, start="2026-01-05T17:00:00", finish="2026-01-05T17:00:00", duration_seconds=0, milestone=True),
            ],
            relationships=[_relationship(1, 1, 2)],
            calendars=[_calendar(1, [("08:00:00", "16:00:00")]), _calendar(2, [("13:00:00", "21:00:00")])],
        )
        comparison = compare_source_coordinates(
            document,
            calculate_forward_schedule(
                build_engine_projection(document, build_calculation_profile(document))
            ),
        )
        self.assertEqual(comparison["counts"]["coordinate_differences"], 0)

    def test_sanitized_evidence_is_deterministic_and_contains_no_names_or_notes(self) -> None:
        document = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400)]
        )
        first = sanitized_profile_evidence(document)
        second = sanitized_profile_evidence(document)
        self.assertEqual(first, second)
        serialized = json.dumps(first)
        self.assertNotIn("Sensitive task", serialized)
        self.assertNotIn("Sensitive notes", serialized)
        self.assertNotIn("Sensitive resource", serialized)
        self.assertNotIn('"activity_id"', serialized)
        self.assertNotIn('"relationship_id"', serialized)
        self.assertNotIn('"differences"', serialized)
        self.assertNotIn("task:", serialized)
        self.assertNotIn("relationship:", serialized)
        self.assertEqual(
            set(first),
            {
                "evidence_profile",
                "claim_boundary",
                "source",
                "source_inventory",
                "profile_counts",
                "reason_counts",
                "primary_reason_counts",
                "comparison",
                "projection_counts",
                "fingerprints",
                "native_project_validation",
                "source_xml_committed",
                "full_canonical_output_committed",
            },
        )
        self.assertEqual(first["native_project_validation"], "not_executed")

    def test_projection_rejects_stale_or_tampered_profile(self) -> None:
        document = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400)]
        )
        profile = build_calculation_profile(document)
        profile["eligible_activity_ids"] = []
        with self.assertRaisesRegex(
            CalculationProfileError, "does not match the supplied canonical document"
        ):
            build_engine_projection(document, profile)

    def test_projection_rejects_profile_from_another_document(self) -> None:
        first = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400)]
        )
        second = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T10:00:00", duration_seconds=7200)]
        )
        profile = build_calculation_profile(first)
        with self.assertRaisesRegex(
            CalculationProfileError, "does not match the supplied canonical document"
        ):
            build_engine_projection(second, profile)

    def test_comparison_rejects_calculation_from_another_document(self) -> None:
        first = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T12:00:00", duration_seconds=14400)]
        )
        second = _document(
            [_activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T10:00:00", duration_seconds=7200)]
        )
        calculation = calculate_forward_schedule(
            build_engine_projection(first, build_calculation_profile(first))
        )
        with self.assertRaisesRegex(
            CalculationProfileError, "does not match the supplied canonical document"
        ):
            compare_source_coordinates(second, calculation)

    def test_cycle_fails_deterministic_forward_pass(self) -> None:
        document = _document(
            [
                _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T10:00:00", duration_seconds=7200),
                _activity(2, start="2026-01-05T10:00:00", finish="2026-01-05T12:00:00", duration_seconds=7200),
            ],
            relationships=[_relationship(1, 1, 2), _relationship(2, 2, 1)],
        )
        projection = build_engine_projection(document, build_calculation_profile(document))
        with self.assertRaisesRegex(CalculationProfileError, "cycle"):
            calculate_forward_schedule(projection)


if __name__ == "__main__":
    unittest.main()
