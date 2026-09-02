from __future__ import annotations

from copy import deepcopy
import unittest

from sto.legacy.calculation_profile import (
    CalculationProfileError,
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
    compare_source_coordinates,
    sanitized_profile_evidence,
    validate_engine_projection,
)

from calculation_fixture import _activity, _document, _relationship


class CalculationContractHardeningTests(unittest.TestCase):
    def test_fractional_duration_and_lag_fail_closed(self) -> None:
        duration_document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T08:00:01.500000",
                    duration_seconds=1.5,
                )
            ]
        )
        duration_record = build_calculation_profile(duration_document)[
            "activities"
        ][0]
        self.assertIn(
            "DURATION_NONINTEGRAL", duration_record["reason_codes"]
        )

        relationship = _relationship(
            1, 1, 2, lag=-(24 * 60 * 10), lag_format=8
        )
        relationship["lag_seconds"] = -86400.5
        lag_document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                ),
                _activity(
                    2,
                    start="2026-01-04T12:00:00",
                    finish="2026-01-04T16:00:00",
                    duration_seconds=14400,
                ),
            ],
            relationships=[relationship],
        )
        lag_record = {
            item["activity_id"]: item
            for item in build_calculation_profile(lag_document)["activities"]
        }["task:2"]
        self.assertIn(
            "RELATIONSHIP_LAG_UNSUPPORTED", lag_record["reason_codes"]
        )

    def test_projection_validator_rejects_duplicate_identifiers(self) -> None:
        document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                ),
                _activity(
                    2,
                    start="2026-01-05T12:00:00",
                    finish="2026-01-05T16:00:00",
                    duration_seconds=14400,
                ),
            ],
            relationships=[_relationship(1, 1, 2)],
        )
        projection = build_engine_projection(
            document, build_calculation_profile(document)
        )

        duplicate_activity = deepcopy(projection)
        duplicate_activity["activities"].append(
            deepcopy(duplicate_activity["activities"][0])
        )
        with self.assertRaisesRegex(
            CalculationProfileError, "duplicate activit"
        ):
            validate_engine_projection(duplicate_activity)

        duplicate_calendar = deepcopy(projection)
        duplicate_calendar["calendars"].append(
            deepcopy(duplicate_calendar["calendars"][0])
        )
        with self.assertRaisesRegex(
            CalculationProfileError, "duplicate calendar"
        ):
            validate_engine_projection(duplicate_calendar)

        duplicate_relationship = deepcopy(projection)
        duplicate_relationship["relationships"].append(
            deepcopy(duplicate_relationship["relationships"][0])
        )
        with self.assertRaisesRegex(
            CalculationProfileError, "duplicate relationship"
        ):
            validate_engine_projection(duplicate_relationship)

    def test_projection_validator_rejects_fractional_engine_values(self) -> None:
        document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                ),
                _activity(
                    2,
                    start="2026-01-05T12:00:00",
                    finish="2026-01-05T16:00:00",
                    duration_seconds=14400,
                ),
            ],
            relationships=[_relationship(1, 1, 2)],
        )
        projection = build_engine_projection(
            document, build_calculation_profile(document)
        )

        fractional_duration = deepcopy(projection)
        fractional_duration["activities"][0]["duration_seconds"] = 1.5
        with self.assertRaisesRegex(
            CalculationProfileError, "integral seconds"
        ):
            validate_engine_projection(fractional_duration)

        fractional_lag = deepcopy(projection)
        fractional_lag["relationships"][0]["lag_seconds"] = -1.5
        fractional_lag["relationships"][0]["lag_basis"] = "elapsed"
        with self.assertRaisesRegex(
            CalculationProfileError, "integral seconds"
        ):
            validate_engine_projection(fractional_lag)

    def test_comparison_requires_the_exact_eligible_activity_cohort(self) -> None:
        document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                ),
                _activity(
                    2,
                    start="2026-01-05T12:00:00",
                    finish="2026-01-05T16:00:00",
                    duration_seconds=14400,
                ),
            ],
            relationships=[_relationship(1, 1, 2)],
        )
        calculation = calculate_forward_schedule(
            build_engine_projection(
                document, build_calculation_profile(document)
            )
        )

        missing = deepcopy(calculation)
        missing["activities"].pop()
        with self.assertRaisesRegex(
            CalculationProfileError, "activity cohort"
        ):
            compare_source_coordinates(document, missing)

        duplicate = deepcopy(calculation)
        duplicate["activities"].append(
            deepcopy(duplicate["activities"][0])
        )
        with self.assertRaisesRegex(
            CalculationProfileError, "duplicate activity ids"
        ):
            compare_source_coordinates(document, duplicate)

    def test_sanitized_evidence_recomputes_and_verifies_supplied_stages(
        self,
    ) -> None:
        document = _document(
            [
                _activity(
                    1,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                )
            ]
        )
        profile = build_calculation_profile(document)
        projection = build_engine_projection(document, profile)
        calculation = calculate_forward_schedule(projection)
        comparison = compare_source_coordinates(document, calculation)

        tampered_profile = deepcopy(profile)
        tampered_profile["counts"]["eligible_activities"] = 0
        with self.assertRaisesRegex(
            CalculationProfileError, "Supplied profile"
        ):
            sanitized_profile_evidence(
                document, profile=tampered_profile
            )

        tampered_projection = deepcopy(projection)
        tampered_projection["activities"][0]["duration_seconds"] = 7200
        with self.assertRaisesRegex(
            CalculationProfileError, "Supplied projection"
        ):
            sanitized_profile_evidence(
                document,
                profile=profile,
                projection=tampered_projection,
            )

        tampered_calculation = deepcopy(calculation)
        tampered_calculation["activities"].clear()
        with self.assertRaisesRegex(
            CalculationProfileError, "Supplied calculation"
        ):
            sanitized_profile_evidence(
                document,
                profile=profile,
                projection=projection,
                calculation=tampered_calculation,
            )

        tampered_comparison = deepcopy(comparison)
        tampered_comparison["counts"]["exact_coordinate_matches"] = 0
        with self.assertRaisesRegex(
            CalculationProfileError, "Supplied comparison"
        ):
            sanitized_profile_evidence(
                document,
                profile=profile,
                projection=projection,
                calculation=calculation,
                comparison=tampered_comparison,
            )


if __name__ == "__main__":
    unittest.main()
