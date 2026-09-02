from __future__ import annotations

from typing import Any

from .calculation_common import CalculationProfileError, _parse_datetime
from .provenance import canonical_sha256

COMPARISON_PROFILE = "calculation-profile-cohort-comparison-v0.1"


def _expected_source(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": document["schema_version"],
        "importer_profile": document["importer_profile"],
        "source_sha256": document["source"]["sha256"],
        "document_key": document["source"]["document_key"],
        "canonical_sha256": canonical_sha256(document),
    }


def _unique_string_ids(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise CalculationProfileError(f"{label} must be a list")
    ids: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise CalculationProfileError(
                f"{label}[{index}] must be a non-empty string"
            )
        ids.append(item)
    if len(ids) != len(set(ids)):
        raise CalculationProfileError(f"{label} contains duplicate ids")
    return ids


def _validate_profile(
    document: dict[str, Any],
    profile: dict[str, Any],
    label: str,
    expected_source: dict[str, Any],
) -> tuple[set[str], set[str]]:
    if not isinstance(profile, dict):
        raise CalculationProfileError(f"{label} profile must be an object")
    if profile.get("source") != expected_source:
        raise CalculationProfileError(
            f"{label} profile does not match the canonical document"
        )
    if not isinstance(profile.get("profile"), str) or not profile["profile"]:
        raise CalculationProfileError(f"{label} profile version is missing")

    activity_ids = set(
        _unique_string_ids(
            profile.get("eligible_activity_ids"),
            f"{label} eligible activity ids",
        )
    )
    relationship_ids = set(
        _unique_string_ids(
            profile.get("eligible_relationship_ids"),
            f"{label} eligible relationship ids",
        )
    )
    counts = profile.get("counts")
    if not isinstance(counts, dict):
        raise CalculationProfileError(f"{label} profile counts are missing")
    expected_counts = {
        "activities": len(document["activities"]),
        "relationships": len(document["relationships"]),
        "eligible_activities": len(activity_ids),
        "excluded_activities": len(document["activities"]) - len(activity_ids),
        "eligible_relationships": len(relationship_ids),
        "excluded_relationships": len(document["relationships"])
        - len(relationship_ids),
    }
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            raise CalculationProfileError(
                f"{label} profile count {key} is inconsistent"
            )
    return activity_ids, relationship_ids


def _count_delta(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, int]:
    keys = sorted(set(baseline) | set(candidate))
    result: dict[str, int] = {}
    for key in keys:
        baseline_value = baseline.get(key, 0)
        candidate_value = candidate.get(key, 0)
        if type(baseline_value) is not int or type(candidate_value) is not int:
            raise CalculationProfileError(
                f"Comparison count {key} must be an integer"
            )
        result[key] = candidate_value - baseline_value
    return result


def _negative_elapsed_fs_lead(
    relationship: dict[str, Any],
    activity_by_id: dict[str, dict[str, Any]],
) -> bool:
    lag = relationship.get("lag_tenths_minutes")
    lag_seconds = relationship.get("lag_seconds")
    successor = activity_by_id.get(relationship.get("successor_ref"))
    return (
        relationship.get("type") == "FS"
        and type(lag) is int
        and lag < 0
        and relationship.get("lag_format_source") == 8
        and type(lag_seconds) is int
        and lag_seconds == lag * 6
        and successor is not None
        and not successor.get("milestone")
    )


def _calculation_by_id(
    calculation: dict[str, Any],
    expected_source: dict[str, Any],
    candidate_profile: dict[str, Any],
    expected_activity_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if calculation.get("source") != expected_source:
        raise CalculationProfileError(
            "Candidate calculation does not match the canonical document"
        )
    if calculation.get("calculation_profile") != candidate_profile.get("profile"):
        raise CalculationProfileError(
            "Candidate calculation profile does not match the candidate eligibility profile"
        )
    rows = calculation.get("activities")
    if not isinstance(rows, list):
        raise CalculationProfileError(
            "Candidate calculation activities must be a list"
        )
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            raise CalculationProfileError(
                f"Candidate calculation activity {index} must be an object"
            )
        activity_id = item.get("id")
        if not isinstance(activity_id, str) or not activity_id:
            raise CalculationProfileError(
                f"Candidate calculation activity {index} has no valid id"
            )
        if activity_id in result:
            raise CalculationProfileError(
                "Candidate calculation contains duplicate activity ids"
            )
        result[activity_id] = item
    if set(result) != expected_activity_ids:
        raise CalculationProfileError(
            "Candidate calculation activity cohort does not match the candidate profile"
        )
    return result


def build_sanitized_profile_comparison(
    document: dict[str, Any],
    baseline_profile: dict[str, Any],
    candidate_profile: dict[str, Any],
    candidate_calculation: dict[str, Any],
) -> dict[str, Any]:
    """Compare two externally generated eligibility profiles without leaking IDs.

    The profiles may be produced by different checked-out code revisions. They must
    refer to the exact same canonical document. The candidate calculation must cover
    the candidate eligible activity set exactly.
    """

    expected_source = _expected_source(document)
    baseline_activity_ids, baseline_relationship_ids = _validate_profile(
        document, baseline_profile, "Baseline", expected_source
    )
    candidate_activity_ids, candidate_relationship_ids = _validate_profile(
        document, candidate_profile, "Candidate", expected_source
    )
    calculation_by_id = _calculation_by_id(
        candidate_calculation,
        expected_source,
        candidate_profile,
        candidate_activity_ids,
    )

    activity_rows = document.get("activities")
    relationship_rows = document.get("relationships")
    if not isinstance(activity_rows, list) or not isinstance(
        relationship_rows, list
    ):
        raise CalculationProfileError(
            "Canonical activities and relationships must be lists"
        )
    activity_by_id: dict[str, dict[str, Any]] = {}
    for item in activity_rows:
        if not isinstance(item, dict):
            raise CalculationProfileError(
                "Canonical activity entry must be an object"
            )
        activity_id = item.get("id")
        if not isinstance(activity_id, str) or not activity_id:
            raise CalculationProfileError("Canonical activity id is missing")
        if activity_id in activity_by_id:
            raise CalculationProfileError(
                "Canonical document contains duplicate activity ids"
            )
        activity_by_id[activity_id] = item

    relationship_by_id: dict[str, dict[str, Any]] = {}
    for item in relationship_rows:
        if not isinstance(item, dict):
            raise CalculationProfileError(
                "Canonical relationship entry must be an object"
            )
        relationship_id = item.get("id")
        if not isinstance(relationship_id, str) or not relationship_id:
            raise CalculationProfileError(
                "Canonical relationship id is missing"
            )
        if relationship_id in relationship_by_id:
            raise CalculationProfileError(
                "Canonical document contains duplicate relationship ids"
            )
        relationship_by_id[relationship_id] = item

    known_activity_ids = set(activity_by_id)
    known_relationship_ids = set(relationship_by_id)
    if not baseline_activity_ids <= known_activity_ids:
        raise CalculationProfileError(
            "Baseline profile references unknown activities"
        )
    if not candidate_activity_ids <= known_activity_ids:
        raise CalculationProfileError(
            "Candidate profile references unknown activities"
        )
    if not baseline_relationship_ids <= known_relationship_ids:
        raise CalculationProfileError(
            "Baseline profile references unknown relationships"
        )
    if not candidate_relationship_ids <= known_relationship_ids:
        raise CalculationProfileError(
            "Candidate profile references unknown relationships"
        )

    newly_eligible_activities = candidate_activity_ids - baseline_activity_ids
    removed_activities = baseline_activity_ids - candidate_activity_ids
    newly_eligible_relationships = (
        candidate_relationship_ids - baseline_relationship_ids
    )
    removed_relationships = (
        baseline_relationship_ids - candidate_relationship_ids
    )

    direct_relationships = {
        relationship_id
        for relationship_id in newly_eligible_relationships
        if _negative_elapsed_fs_lead(
            relationship_by_id[relationship_id], activity_by_id
        )
    }
    direct_successors = {
        relationship_by_id[relationship_id]["successor_ref"]
        for relationship_id in direct_relationships
    } & newly_eligible_activities
    downstream_activities = newly_eligible_activities - direct_successors
    other_new_relationships = newly_eligible_relationships - direct_relationships

    difference_ids: list[str] = []
    exact = 0
    for activity_id in sorted(newly_eligible_activities):
        source = activity_by_id[activity_id]
        calculated = calculation_by_id[activity_id]
        source_start = _parse_datetime(source.get("start"))
        source_finish = _parse_datetime(source.get("finish"))
        calculated_start = _parse_datetime(calculated.get("calculated_start"))
        calculated_finish = _parse_datetime(
            calculated.get("calculated_finish")
        )
        if (
            calculated_start == source_start
            and calculated_finish == source_finish
        ):
            exact += 1
        else:
            difference_ids.append(activity_id)

    baseline_counts = dict(baseline_profile["counts"])
    candidate_counts = dict(candidate_profile["counts"])
    baseline_reasons = dict(baseline_profile.get("reason_counts", {}))
    candidate_reasons = dict(candidate_profile.get("reason_counts", {}))
    baseline_primary = dict(
        baseline_profile.get("primary_reason_counts", {})
    )
    candidate_primary = dict(
        candidate_profile.get("primary_reason_counts", {})
    )

    return {
        "comparison_profile": COMPARISON_PROFILE,
        "claim_boundary": (
            "Sanitized cohort comparison between two deterministic eligibility profiles "
            "for the same canonical source. This is not native Microsoft Project validation."
        ),
        "source": expected_source,
        "baseline": {
            "calculation_profile": baseline_profile["profile"],
            "profile_sha256": canonical_sha256(baseline_profile),
            "eligible_activity_ids_sha256": canonical_sha256(
                sorted(baseline_activity_ids)
            ),
            "eligible_relationship_ids_sha256": canonical_sha256(
                sorted(baseline_relationship_ids)
            ),
        },
        "candidate": {
            "calculation_profile": candidate_profile["profile"],
            "profile_sha256": canonical_sha256(candidate_profile),
            "calculation_sha256": canonical_sha256(candidate_calculation),
            "eligible_activity_ids_sha256": canonical_sha256(
                sorted(candidate_activity_ids)
            ),
            "eligible_relationship_ids_sha256": canonical_sha256(
                sorted(candidate_relationship_ids)
            ),
        },
        "profile_counts": {
            "baseline": baseline_counts,
            "candidate": candidate_counts,
            "delta": _count_delta(baseline_counts, candidate_counts),
        },
        "reason_counts": {
            "baseline": baseline_reasons,
            "candidate": candidate_reasons,
            "delta": _count_delta(baseline_reasons, candidate_reasons),
        },
        "primary_reason_counts": {
            "baseline": baseline_primary,
            "candidate": candidate_primary,
            "delta": _count_delta(baseline_primary, candidate_primary),
        },
        "changed_cohorts": {
            "newly_eligible_activities": len(newly_eligible_activities),
            "newly_eligible_activity_ids_sha256": canonical_sha256(
                sorted(newly_eligible_activities)
            ),
            "removed_eligible_activities": len(removed_activities),
            "removed_eligible_activity_ids_sha256": canonical_sha256(
                sorted(removed_activities)
            ),
            "newly_eligible_relationships": len(
                newly_eligible_relationships
            ),
            "newly_eligible_relationship_ids_sha256": canonical_sha256(
                sorted(newly_eligible_relationships)
            ),
            "removed_eligible_relationships": len(removed_relationships),
            "removed_eligible_relationship_ids_sha256": canonical_sha256(
                sorted(removed_relationships)
            ),
            "direct_negative_elapsed_fs_lead_relationships": len(
                direct_relationships
            ),
            "direct_negative_elapsed_fs_lead_relationship_ids_sha256": canonical_sha256(
                sorted(direct_relationships)
            ),
            "direct_negative_elapsed_fs_lead_successors": len(
                direct_successors
            ),
            "direct_negative_elapsed_fs_lead_successor_activity_ids_sha256": canonical_sha256(
                sorted(direct_successors)
            ),
            "downstream_dependency_closure_activities": len(
                downstream_activities
            ),
            "downstream_dependency_closure_activity_ids_sha256": canonical_sha256(
                sorted(downstream_activities)
            ),
            "other_newly_eligible_relationships": len(
                other_new_relationships
            ),
            "other_newly_eligible_relationship_ids_sha256": canonical_sha256(
                sorted(other_new_relationships)
            ),
        },
        "changed_cohort_comparison": {
            "compared_activities": len(newly_eligible_activities),
            "exact_coordinate_matches": exact,
            "coordinate_differences": len(difference_ids),
            "difference_activity_ids_sha256": canonical_sha256(
                sorted(difference_ids)
            ),
        },
        "native_project_validation": "not_executed",
    }
