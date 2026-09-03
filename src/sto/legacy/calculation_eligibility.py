from __future__ import annotations

from collections import Counter
from typing import Any

from .calculation_activity import classify_local_activities
from .calculation_calendar import _pattern_payload
from .calculation_common import (
    PROFILE_VERSION,
    SUPPORTED_IMPORTER_PROFILE,
    SUPPORTED_NEGATIVE_ELAPSED_LAG_FORMAT,
    SUPPORTED_RELATIONSHIP_TYPES,
    SUPPORTED_SCHEMA_VERSION,
    CalculationProfileError,
    _duration_seconds,
    _first_reason,
    _is_integral_seconds,
)
from .provenance import canonical_sha256


def _relationship_lag_supported(
    relationship: dict[str, Any], activity_by_id: dict[str, dict[str, Any]]
) -> bool:
    lag = relationship.get("lag_tenths_minutes")
    lag_seconds = relationship.get("lag_seconds")
    if type(lag) is not int or not _is_integral_seconds(lag_seconds):
        return False
    if lag == 0:
        return lag_seconds == 0
    if lag >= 0:
        return False
    if relationship.get("lag_format_source") != SUPPORTED_NEGATIVE_ELAPSED_LAG_FORMAT:
        return False
    if lag_seconds != lag * 6:
        return False
    successor = activity_by_id.get(relationship.get("successor_ref"))
    if successor is None or successor.get("milestone"):
        return False
    return True


def build_calculation_profile(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise CalculationProfileError(
            f"Profile {PROFILE_VERSION} requires schema {SUPPORTED_SCHEMA_VERSION}"
        )
    if document.get("importer_profile") != SUPPORTED_IMPORTER_PROFILE:
        raise CalculationProfileError(
            f"Profile {PROFILE_VERSION} requires importer {SUPPORTED_IMPORTER_PROFILE}"
        )
    if document.get("project", {}).get("schedule_from_start") is not True:
        raise CalculationProfileError(
            "The bounded calculation profile supports schedule-from-start projects only"
        )

    local = classify_local_activities(document)
    activity_by_id = local["activity_by_id"]
    reasons = local["reasons"]
    effective_patterns = local["effective_patterns"]
    calendar_lineage = local["calendar_lineage"]
    ignored_exception_counts = local["ignored_exception_counts"]

    for activity_id, activity in activity_by_id.items():
        duration_seconds = _duration_seconds(activity.get("duration"))
        if duration_seconds is not None and not _is_integral_seconds(duration_seconds):
            reasons[activity_id].add("DURATION_NONINTEGRAL")

    activity_ids = set(activity_by_id)
    supported_relationship_ids: set[str] = set()
    for relationship in document["relationships"]:
        predecessor = relationship.get("predecessor_ref")
        successor = relationship.get("successor_ref")
        if predecessor not in activity_ids or successor not in activity_ids:
            if successor in reasons:
                reasons[successor].add("RELATIONSHIP_ENDPOINT_UNSUPPORTED")
            continue
        relation_supported = True
        if relationship.get("type") not in SUPPORTED_RELATIONSHIP_TYPES:
            reasons[successor].add("RELATIONSHIP_TYPE_UNSUPPORTED")
            relation_supported = False
        if not _relationship_lag_supported(relationship, activity_by_id):
            reasons[successor].add("RELATIONSHIP_LAG_UNSUPPORTED")
            relation_supported = False
        if relationship.get("cross_project"):
            reasons[successor].add("CROSS_PROJECT_RELATIONSHIP_UNSUPPORTED")
            relation_supported = False
        if relationship.get("extensions"):
            reasons[successor].add("RELATIONSHIP_EXTENSION_UNSUPPORTED")
            relation_supported = False
        if relation_supported:
            supported_relationship_ids.add(relationship["id"])

    changed = True
    while changed:
        changed = False
        for relationship in document["relationships"]:
            predecessor = relationship.get("predecessor_ref")
            successor = relationship.get("successor_ref")
            if predecessor not in reasons or successor not in reasons:
                continue
            if reasons[predecessor] and "INELIGIBLE_PREDECESSOR" not in reasons[successor]:
                reasons[successor].add("INELIGIBLE_PREDECESSOR")
                changed = True

    eligible_activity_ids = {
        activity_id for activity_id, activity_reasons in reasons.items() if not activity_reasons
    }
    eligible_relationship_ids = {
        relationship["id"]
        for relationship in document["relationships"]
        if relationship["id"] in supported_relationship_ids
        and relationship.get("predecessor_ref") in eligible_activity_ids
        and relationship.get("successor_ref") in eligible_activity_ids
    }

    activity_records = []
    for activity in sorted(
        document["activities"], key=lambda item: (item["source_order"], item["id"])
    ):
        activity_reasons = tuple(sorted(reasons[activity["id"]]))
        pattern = effective_patterns.get(activity["id"])
        activity_records.append(
            {
                "activity_id": activity["id"],
                "source_order": activity["source_order"],
                "eligible": not activity_reasons,
                "reason_codes": list(activity_reasons),
                "primary_reason": _first_reason(activity_reasons)
                if activity_reasons
                else None,
                "effective_calendar_fingerprint": canonical_sha256(
                    _pattern_payload(pattern)
                )
                if pattern is not None
                else None,
                "calendar_source_lineage": list(
                    calendar_lineage.get(activity["id"], ())
                ),
                "ignored_nonoverlapping_exception_count": ignored_exception_counts.get(
                    activity["id"], 0
                ),
            }
        )

    reason_counts = Counter(
        reason for activity_reasons in reasons.values() for reason in activity_reasons
    )
    primary_reason_counts = Counter(
        _first_reason(activity_reasons)
        for activity_reasons in reasons.values()
        if activity_reasons
    )

    return {
        "profile": PROFILE_VERSION,
        "claim_boundary": (
            "Eligibility and engine-input classification only. This is not a Microsoft Project "
            "calculation, float, critical-path, export or round-trip compatibility claim."
        ),
        "source": {
            "schema_version": document["schema_version"],
            "importer_profile": document["importer_profile"],
            "source_sha256": document["source"]["sha256"],
            "document_key": document["source"]["document_key"],
            "canonical_sha256": canonical_sha256(document),
        },
        "supported_semantics": {
            "schedule_direction": "from start",
            "constraints": ["ASAP"],
            "relationships": [
                "FS with zero lag",
                "FS with negative lag where LagFormat=8 (pjElapsedDays); lead is continuous elapsed time",
            ],
            "duration_formats": ["hours (source code 5)"],
            "progress": "not started only",
            "calendar_inheritance": "resolved recursively",
            "calendar_exceptions": (
                "permitted only when wholly outside the project, source-coordinate and "
                "supported lead-candidate horizon"
            ),
            "resource_calendars": (
                "one effective resource pattern, or identical patterns across assignments; "
                "explicit task calendars intersect unless IgnoreResourceCalendar is set"
            ),
            "milestones": (
                "zero-duration milestones retain predecessor time without working-time snap; "
                "negative-lag links into milestones remain unsupported"
            ),
        },
        "counts": {
            "activities": len(document["activities"]),
            "eligible_activities": len(eligible_activity_ids),
            "excluded_activities": len(document["activities"]) - len(eligible_activity_ids),
            "eligible_milestones": sum(
                1
                for activity_id in eligible_activity_ids
                if activity_by_id[activity_id].get("milestone")
            ),
            "eligible_non_milestones": sum(
                1
                for activity_id in eligible_activity_ids
                if not activity_by_id[activity_id].get("milestone")
            ),
            "relationships": len(document["relationships"]),
            "eligible_relationships": len(eligible_relationship_ids),
            "excluded_relationships": len(document["relationships"]) - len(eligible_relationship_ids),
        },
        "reason_counts": dict(sorted(reason_counts.items())),
        "primary_reason_counts": dict(sorted(primary_reason_counts.items())),
        "activities": activity_records,
        "eligible_activity_ids": sorted(eligible_activity_ids),
        "eligible_relationship_ids": sorted(eligible_relationship_ids),
    }
