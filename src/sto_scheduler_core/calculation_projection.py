from __future__ import annotations

from collections import defaultdict
from typing import Any

from .calculation_activity import _extension_values, _one_extension_value
from .calculation_calendar import _CalendarResolver, _intersect_patterns, _pattern_payload
from .calculation_common import CalculationProfileError, PROFILE_VERSION, _duration_seconds
from .calculation_eligibility import build_calculation_profile
from .calculation_engine import calculate_forward_schedule, compare_source_coordinates
from .provenance import canonical_sha256


def build_engine_projection(
    document: dict[str, Any], profile: dict[str, Any] | None = None
) -> dict[str, Any]:
    expected_profile = build_calculation_profile(document)
    if profile is None:
        profile = expected_profile
    elif canonical_sha256(profile) != canonical_sha256(expected_profile):
        raise CalculationProfileError(
            "Calculation profile does not match the supplied canonical document"
        )
    if profile.get("profile") != PROFILE_VERSION:
        raise CalculationProfileError("Unexpected calculation profile")

    eligible_activity_ids = set(profile["eligible_activity_ids"])
    eligible_relationship_ids = set(profile["eligible_relationship_ids"])
    profile_by_activity = {item["activity_id"]: item for item in profile["activities"]}
    activity_by_id = {item["id"]: item for item in document["activities"]}

    calendar_by_fingerprint: dict[str, dict[str, Any]] = {}
    resolver = _CalendarResolver(document)
    extension_by_id = {item["id"]: item for item in document.get("vendor_extensions", [])}
    resource_by_id = {item["id"]: item for item in document["resources"]}
    assignments_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assignment in document["assignments"]:
        assignments_by_task[assignment.get("task_ref")].append(assignment)

    activities = []
    for activity_id in sorted(
        eligible_activity_ids,
        key=lambda item: (activity_by_id[item]["source_order"], item),
    ):
        activity = activity_by_id[activity_id]
        extension_values = _extension_values(activity, extension_by_id)
        ignore_resource_calendar = _one_extension_value(extension_values, "IgnoreResourceCalendar")
        explicit_task_ref = activity.get("calendar_ref")
        task_calendar = resolver.resolve(explicit_task_ref or document["project"].get("calendar_ref"))
        resource_calendars = []
        for assignment in assignments_by_task.get(activity_id, []):
            resource_ref = assignment.get("resource_ref")
            if resource_ref is None:
                continue
            resource_calendars.append(resolver.resolve(resource_by_id[resource_ref].get("calendar_ref")))
        distinct_resource_patterns = {item.pattern for item in resource_calendars}
        if explicit_task_ref is not None:
            if ignore_resource_calendar == "1" or not resource_calendars:
                pattern = task_calendar.pattern
            else:
                pattern = _intersect_patterns(task_calendar.pattern, resource_calendars[0].pattern)
        elif distinct_resource_patterns:
            pattern = resource_calendars[0].pattern
        else:
            pattern = task_calendar.pattern

        fingerprint = canonical_sha256(_pattern_payload(pattern))
        expected_fingerprint = profile_by_activity[activity_id]["effective_calendar_fingerprint"]
        if fingerprint != expected_fingerprint:
            raise CalculationProfileError(f"Effective calendar drift for eligible activity {activity_id}")
        calendar_id = f"effective-calendar:{fingerprint}"
        calendar_by_fingerprint.setdefault(
            fingerprint,
            {"id": calendar_id, "fingerprint": fingerprint, "week": _pattern_payload(pattern)},
        )
        duration_seconds = _duration_seconds(activity.get("duration"))
        if duration_seconds is None:
            raise CalculationProfileError(f"Eligible activity {activity_id} has no parsed duration")
        activities.append(
            {
                "id": activity_id,
                "source_order": activity["source_order"],
                "duration_seconds": duration_seconds,
                "milestone": bool(activity.get("milestone")),
                "constraint": "ASAP",
                "effective_calendar_ref": calendar_id,
                "profile_calendar_fingerprint": expected_fingerprint,
            }
        )

    relationships = []
    for relationship in sorted(
        document["relationships"], key=lambda item: (item["source_order"], item["id"])
    ):
        if relationship["id"] not in eligible_relationship_ids:
            continue
        lag_seconds = relationship.get("lag_seconds")
        if not isinstance(lag_seconds, (int, float)) or lag_seconds > 0:
            raise CalculationProfileError(f"Eligible relationship {relationship['id']} has unsupported lag")
        relationships.append(
            {
                "id": relationship["id"],
                "source_order": relationship["source_order"],
                "predecessor_ref": relationship["predecessor_ref"],
                "successor_ref": relationship["successor_ref"],
                "type": "FS",
                "lag_seconds": lag_seconds,
                "lag_basis": "elapsed" if lag_seconds < 0 else "none",
            }
        )

    return {
        "projection_profile": PROFILE_VERSION,
        "claim_boundary": (
            "Engine-neutral forward-pass input for the declared eligible subset only. "
            "Source task names, source early/late dates, source slack and Project critical flags are not inputs."
        ),
        "source": profile["source"],
        "project": {"schedule_from_start": True, "start": document["project"]["start"]},
        "calendars": [calendar_by_fingerprint[key] for key in sorted(calendar_by_fingerprint)],
        "activities": activities,
        "relationships": relationships,
    }


def sanitized_profile_evidence(
    document: dict[str, Any],
    profile: dict[str, Any] | None = None,
    projection: dict[str, Any] | None = None,
    calculation: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = profile or build_calculation_profile(document)
    projection = projection or build_engine_projection(document, profile)
    calculation = calculation or calculate_forward_schedule(projection)
    comparison = comparison or compare_source_coordinates(document, calculation)
    eligible_activity_ids = profile["eligible_activity_ids"]
    excluded_activity_ids = sorted(
        item["activity_id"] for item in profile["activities"] if not item["eligible"]
    )
    return {
        "evidence_profile": f"{PROFILE_VERSION}-sanitized-evidence-v0.1",
        "claim_boundary": comparison["claim_boundary"],
        "source": profile["source"],
        "source_inventory": {
            key: document["source_inventory"][key]
            for key in (
                "tasks", "summary_tasks", "leaf_activities", "milestones",
                "activity_milestones", "summary_milestones", "relationships",
                "relationship_types", "calendars", "resources", "assignments",
                "baselines", "custom_field_definitions", "vendor_extensions",
            )
        }
        | {
            "preserved_extension_element_counts_sha256": canonical_sha256(
                document["source_inventory"].get("preserved_extension_element_counts", {})
            )
        },
        "profile_counts": profile["counts"],
        "reason_counts": profile["reason_counts"],
        "primary_reason_counts": profile["primary_reason_counts"],
        "comparison": comparison["counts"],
        "projection_counts": {
            "activities": len(projection["activities"]),
            "relationships": len(projection["relationships"]),
            "effective_calendars": len(projection["calendars"]),
        },
        "fingerprints": {
            "eligible_activity_ids_sha256": canonical_sha256(sorted(eligible_activity_ids)),
            "excluded_activity_ids_sha256": canonical_sha256(excluded_activity_ids),
            "eligible_relationship_ids_sha256": canonical_sha256(sorted(profile["eligible_relationship_ids"])),
            "profile_sha256": canonical_sha256(profile),
            "projection_sha256": canonical_sha256(projection),
            "calculation_sha256": canonical_sha256(calculation),
            "difference_activity_ids_sha256": comparison["difference_activity_ids_sha256"],
        },
        "native_project_validation": "not_executed",
        "source_xml_committed": False,
        "full_canonical_output_committed": False,
    }
