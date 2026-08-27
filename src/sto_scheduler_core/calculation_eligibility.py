from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from typing import Any, Iterable

ELIGIBILITY_PROFILE = "sto-calculation-eligibility-v0.1"
SUPPORTED_RELATIONSHIP_TYPES = frozenset({"FS", "SS", "FF", "SF"})
SUPPORTED_CONSTRAINT_TYPES = frozenset({0, 4, 6})


def _duration_seconds(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    seconds = value.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        return None
    return seconds


def _stable_hash(values: Iterable[str]) -> str:
    payload = json.dumps(sorted(set(values)), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(payload).hexdigest()


def _effective_calendar_ref(activity: dict[str, Any], project: dict[str, Any]) -> str | None:
    value = activity.get("calendar_ref")
    if isinstance(value, str) and value:
        return value
    project_value = project.get("calendar_ref")
    return project_value if isinstance(project_value, str) and project_value else None


def _calendar_has_exceptions(calendar: dict[str, Any]) -> bool:
    for key in ("exceptions", "exception_days", "calendar_exceptions"):
        value = calendar.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _calendar_has_working_week(calendar: dict[str, Any]) -> bool:
    week_days = calendar.get("week_days")
    if not isinstance(week_days, list) or not week_days:
        return False
    for day in week_days:
        if not isinstance(day, dict):
            continue
        working_times = day.get("working_times")
        if isinstance(working_times, list) and working_times:
            return True
    return False


def _progress_reasons(activity: dict[str, Any]) -> set[str]:
    reasons: set[str] = set()
    for key in (
        "percent_complete_source",
        "percent_work_complete_source",
        "physical_percent_complete_source",
    ):
        value = activity.get(key)
        if value not in (None, 0):
            reasons.add("progress_state")

    for key in ("actual_start_source", "actual_finish_source"):
        if activity.get(key) not in (None, ""):
            reasons.add("actual_state")

    for key in ("actual_duration_source", "actual_work_source"):
        seconds = _duration_seconds(activity.get(key))
        if seconds not in (None, 0):
            reasons.add("actual_state")

    duration_seconds = _duration_seconds(activity.get("duration"))
    remaining_seconds = _duration_seconds(activity.get("remaining_duration_source"))
    if remaining_seconds is not None and duration_seconds is not None and remaining_seconds != duration_seconds:
        reasons.add("remaining_state_differs_from_duration")

    return reasons


def classify_calculation_eligibility(document: dict[str, Any]) -> dict[str, Any]:
    """Classify a fail-closed, source-independent schedule-calculation cohort.

    The result is intentionally more conservative than a normal importer. It
    identifies activities whose currently represented semantics fit the first
    bounded calculation experiment. It does not calculate a schedule and does
    not claim Microsoft Project compatibility.
    """

    project = document.get("project") if isinstance(document.get("project"), dict) else {}
    activities = [item for item in document.get("activities", []) if isinstance(item, dict)]
    relationships = [item for item in document.get("relationships", []) if isinstance(item, dict)]
    calendars = {
        item.get("id"): item
        for item in document.get("calendars", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    resources = {
        item.get("id"): item
        for item in document.get("resources", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    assignments_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assignment in document.get("assignments", []):
        if not isinstance(assignment, dict):
            continue
        task_ref = assignment.get("task_ref")
        if isinstance(task_ref, str):
            assignments_by_task[task_ref].append(assignment)

    activity_by_id = {
        item.get("id"): item
        for item in activities
        if isinstance(item.get("id"), str) and item.get("id")
    }
    local_reasons: dict[str, set[str]] = {activity_id: set() for activity_id in activity_by_id}

    for activity_id, activity in activity_by_id.items():
        reasons = local_reasons[activity_id]
        if activity.get("active") is False:
            reasons.add("inactive")
        if activity.get("manual") is True:
            reasons.add("manual_scheduling")
        if activity.get("is_null_source") is True:
            reasons.add("null_source_task")

        start = activity.get("start")
        finish = activity.get("finish")
        if not isinstance(start, str) or not start:
            reasons.add("missing_start")
        if not isinstance(finish, str) or not finish:
            reasons.add("missing_finish")

        duration_seconds = _duration_seconds(activity.get("duration"))
        if duration_seconds is None:
            reasons.add("unparsed_duration")
        elif activity.get("milestone") is True and duration_seconds != 0:
            reasons.add("invalid_milestone_duration")
        elif activity.get("milestone") is not True and duration_seconds <= 0:
            reasons.add("nonpositive_activity_duration")

        reasons.update(_progress_reasons(activity))

        if activity.get("deadline_source") not in (None, ""):
            reasons.add("deadline")

        constraint_type = activity.get("constraint_type_source")
        if constraint_type is None:
            constraint_type = 0
        if constraint_type not in SUPPORTED_CONSTRAINT_TYPES:
            reasons.add("unsupported_constraint")
        elif constraint_type in {4, 6} and activity.get("constraint_date_source") in (None, ""):
            reasons.add("constraint_date_missing")

        calendar_ref = _effective_calendar_ref(activity, project)
        if calendar_ref is None:
            reasons.add("calendar_unresolved")
        else:
            calendar = calendars.get(calendar_ref)
            if calendar is None:
                reasons.add("calendar_unresolved")
            else:
                if calendar.get("base_calendar_ref") not in (None, ""):
                    reasons.add("calendar_inheritance")
                if _calendar_has_exceptions(calendar):
                    reasons.add("calendar_exceptions")
                if not _calendar_has_working_week(calendar):
                    reasons.add("calendar_has_no_working_week")

        for assignment in assignments_by_task.get(activity_id, []):
            resource_ref = assignment.get("resource_ref")
            if resource_ref is None:
                continue
            resource = resources.get(resource_ref)
            if resource is None:
                reasons.add("assignment_resource_unresolved")
                continue
            resource_calendar = resource.get("calendar_ref")
            if resource_calendar not in (None, "", calendar_ref):
                reasons.add("resource_calendar_interaction")

    relation_reasons: dict[str, set[str]] = defaultdict(set)
    supported_relations: list[dict[str, Any]] = []
    for relationship in relationships:
        relation_id = relationship.get("id")
        predecessor = relationship.get("predecessor_ref")
        successor = relationship.get("successor_ref")
        relationship_type = relationship.get("type")
        reasons: set[str] = set()
        if predecessor not in activity_by_id or successor not in activity_by_id:
            reasons.add("non_activity_endpoint")
        if relationship_type not in SUPPORTED_RELATIONSHIP_TYPES:
            reasons.add("unsupported_relationship_type")
        lag = relationship.get("lag_tenths_minutes")
        if isinstance(lag, bool) or not isinstance(lag, int):
            reasons.add("invalid_relationship_lag")
        if relationship.get("cross_project") is True:
            reasons.add("cross_project_relationship")
        if reasons:
            if isinstance(relation_id, str):
                relation_reasons[relation_id].update(reasons)
            for endpoint in (predecessor, successor):
                if endpoint in local_reasons:
                    local_reasons[endpoint].add("unsupported_adjacent_relationship")
        else:
            supported_relations.append(relationship)

    # A calculation cohort must be closed over its represented activity network.
    # An activity connected to an ineligible neighbour is removed so the engine
    # cannot silently treat an unsupported predecessor/successor as an open end.
    eligible = {activity_id for activity_id, reasons in local_reasons.items() if not reasons}
    closure_reasons: dict[str, set[str]] = defaultdict(set)
    changed = True
    while changed:
        changed = False
        for relationship in supported_relations:
            predecessor = relationship["predecessor_ref"]
            successor = relationship["successor_ref"]
            predecessor_eligible = predecessor in eligible
            successor_eligible = successor in eligible
            if predecessor_eligible and not successor_eligible:
                eligible.remove(predecessor)
                closure_reasons[predecessor].add("network_has_ineligible_successor")
                changed = True
            elif successor_eligible and not predecessor_eligible:
                eligible.remove(successor)
                closure_reasons[successor].add("network_has_ineligible_predecessor")
                changed = True

    excluded_reasons: dict[str, list[str]] = {}
    for activity_id in sorted(activity_by_id):
        reasons = set(local_reasons[activity_id])
        reasons.update(closure_reasons.get(activity_id, set()))
        if activity_id not in eligible:
            if not reasons:
                reasons.add("network_closure")
            excluded_reasons[activity_id] = sorted(reasons)

    eligible_relationship_ids = sorted(
        relationship["id"]
        for relationship in supported_relations
        if relationship.get("predecessor_ref") in eligible
        and relationship.get("successor_ref") in eligible
        and isinstance(relationship.get("id"), str)
    )
    reason_counts = Counter(
        reason
        for reasons in excluded_reasons.values()
        for reason in reasons
    )
    relationship_reason_counts = Counter(
        reason
        for reasons in relation_reasons.values()
        for reason in reasons
    )

    return {
        "profile": ELIGIBILITY_PROFILE,
        "claim_boundary": (
            "Eligibility classification only. No schedule calculation, Microsoft Project semantic "
            "equivalence, or native compatibility claim is made."
        ),
        "eligible_activity_ids": sorted(eligible),
        "eligible_relationship_ids": eligible_relationship_ids,
        "excluded_activity_reasons": excluded_reasons,
        "unsupported_relationship_reasons": {
            key: sorted(value) for key, value in sorted(relation_reasons.items())
        },
        "counts": {
            "activities": len(activity_by_id),
            "eligible_activities": len(eligible),
            "excluded_activities": len(activity_by_id) - len(eligible),
            "relationships": len(relationships),
            "eligible_relationships": len(eligible_relationship_ids),
            "unsupported_relationships": len(relation_reasons),
        },
        "activity_exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "relationship_exclusion_reason_counts": dict(sorted(relationship_reason_counts.items())),
    }


def sanitized_eligibility_evidence(result: dict[str, Any]) -> dict[str, Any]:
    """Return evidence with counts and set fingerprints but no source descriptions."""

    eligible_ids = [str(value) for value in result.get("eligible_activity_ids", [])]
    eligible_relationship_ids = [str(value) for value in result.get("eligible_relationship_ids", [])]
    excluded = result.get("excluded_activity_reasons", {})
    reason_sets: dict[str, list[str]] = defaultdict(list)
    if isinstance(excluded, dict):
        for activity_id, reasons in excluded.items():
            if not isinstance(reasons, list):
                continue
            for reason in reasons:
                reason_sets[str(reason)].append(str(activity_id))

    return {
        "profile": result.get("profile"),
        "claim_boundary": result.get("claim_boundary"),
        "counts": result.get("counts", {}),
        "activity_exclusion_reason_counts": result.get("activity_exclusion_reason_counts", {}),
        "relationship_exclusion_reason_counts": result.get("relationship_exclusion_reason_counts", {}),
        "set_fingerprints": {
            "eligible_activity_ids_sha256": _stable_hash(eligible_ids),
            "eligible_relationship_ids_sha256": _stable_hash(eligible_relationship_ids),
            "excluded_activity_ids_by_reason_sha256": {
                reason: _stable_hash(values) for reason, values in sorted(reason_sets.items())
            },
        },
    }
