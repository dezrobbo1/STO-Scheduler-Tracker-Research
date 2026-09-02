from __future__ import annotations

from copy import deepcopy
import unittest

from sto_scheduler_core.calculation_profile import (
    CalculationProfileError,
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
)
from sto_scheduler_core.profile_comparison import (
    COMPARISON_PROFILE,
    build_sanitized_profile_comparison,
)

from calculation_fixture import _activity, _document, _relationship


ELAPSED_DAY_TENTHS = 24 * 60 * 10


def _baseline_from_candidate(candidate: dict[str, object]) -> dict[str, object]:
    baseline = deepcopy(candidate)
    baseline["profile"] = "mspdi-calculation-eligibility-v0.1"
    baseline["eligible_activity_ids"] = ["task:1"]
    baseline["eligible_relationship_ids"] = []
    baseline["counts"] = {
        "activities": 3,
        "eligible_activities": 1,
        "excluded_activities": 2,
        "eligible_milestones": 0,
        "eligible_non_milestones": 1,
        "relationships": 2,
        "eligible_relationships": 0,
        "excluded_relationships": 2,
    }
    baseline["reason_counts"] = {
        "INELIGIBLE_PREDECESSOR": 1,
        "RELATIONSHIP_LAG_UNSUPPORTED": 1,
    }
    baseline["primary_reason_counts"] = {
        "INELIGIBLE_PREDECESSOR": 1,
        "RELATIONSHIP_LAG_UNSUPPORTED": 1,
    }
    return baseline


class ProfileComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = _document(
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
                _activity(
                    3,
                    start="2026-01-05T08:00:00",
                    finish="2026-01-05T12:00:00",
                    duration_seconds=14400,
                ),
            ],
            relationships=[
                _relationship(
                    1,
                    1,
                    2,
                    lag=-ELAPSED_DAY_TENTHS,
                    lag_format=8,
                ),
                _relationship(2, 2, 3),
            ],
        )
        self.candidate_profile = build_calculation_profile(self.document)
        self.baseline_profile = _baseline_from_candidate(
            self.candidate_profile
        )
        self.candidate_calculation = calculate_forward_schedule(
            build_engine_projection(
                self.document, self.candidate_profile
            )
        )

    def test_comparison_classifies_direct_and_downstream_additions(self) -> None:
        result = build_sanitized_profile_comparison(
            self.document,
            self.baseline_profile,
            self.candidate_profile,
            self.candidate_calculation,
        )
        self.assertEqual(result["comparison_profile"], COMPARISON_PROFILE)
        self.assertEqual(
            result["changed_cohorts"]["newly_eligible_activities"], 2
        )
        self.assertEqual(
            result["changed_cohorts"][
                "direct_negative_elapsed_fs_lead_relationships"
            ],
            1,
        )
        self.assertEqual(
            result["changed_cohorts"][
                "direct_negative_elapsed_fs_lead_successors"
            ],
            1,
        )
        self.assertEqual(
            result["changed_cohorts"][
                "downstream_dependency_closure_activities"
            ],
            1,
        )
        self.assertEqual(
            result["changed_cohorts"]["newly_eligible_relationships"], 2
        )
        self.assertEqual(
            result["changed_cohorts"][
                "other_newly_eligible_relationships"
            ],
            1,
        )
        self.assertEqual(
            result["changed_cohort_comparison"],
            {
                "compared_activities": 2,
                "exact_coordinate_matches": 2,
                "coordinate_differences": 0,
                "difference_activity_ids_sha256": (
                    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
                ),
            },
        )
        self.assertEqual(
            result["native_project_validation"], "not_executed"
        )

        def assert_no_lists(value: object) -> None:
            self.assertNotIsInstance(value, list)
            if isinstance(value, dict):
                for child in value.values():
                    assert_no_lists(child)

        assert_no_lists(result)
        serialized = str(result)
        self.assertNotIn("task:", serialized)
        self.assertNotIn("relationship:", serialized)

    def test_comparison_rejects_incomplete_candidate_calculation(self) -> None:
        calculation = deepcopy(self.candidate_calculation)
        calculation["activities"].pop()
        with self.assertRaisesRegex(
            CalculationProfileError, "activity cohort"
        ):
            build_sanitized_profile_comparison(
                self.document,
                self.baseline_profile,
                self.candidate_profile,
                calculation,
            )

    def test_comparison_rejects_profile_from_another_document(self) -> None:
        baseline = deepcopy(self.baseline_profile)
        baseline["source"]["canonical_sha256"] = "b" * 64
        with self.assertRaisesRegex(
            CalculationProfileError, "does not match"
        ):
            build_sanitized_profile_comparison(
                self.document,
                baseline,
                self.candidate_profile,
                self.candidate_calculation,
            )


if __name__ == "__main__":
    unittest.main()
