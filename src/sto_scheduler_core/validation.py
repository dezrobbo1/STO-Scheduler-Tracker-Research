from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(slots=True)
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


def _unique_ids(
    items: Iterable[dict[str, Any]], label: str, report: ValidationReport
) -> set[str]:
    seen: set[str] = set()
    for item in items:
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            report.errors.append(f"{label} contains an item without a non-empty string id")
            continue
        if item_id in seen:
            report.errors.append(f"Duplicate {label} id: {item_id}")
        seen.add(item_id)
    return seen


def _check_wbs_cycles(
    nodes: list[dict[str, Any]], report: ValidationReport
) -> None:
    parents = {
        node["id"]: node.get("parent_id")
        for node in nodes
        if isinstance(node.get("id"), str)
    }
    for node_id in parents:
        current = node_id
        path: set[str] = set()
        while current is not None:
            if current in path:
                report.errors.append(
                    f"WBS parent cycle detected from {node_id}: {current}"
                )
                break
            path.add(current)
            parent = parents.get(current)
            if parent is not None and parent not in parents:
                report.errors.append(
                    f"WBS node {current} references missing parent {parent}"
                )
                break
            current = parent


def _check_outline_hierarchy(
    wbs_nodes: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    report: ValidationReport,
) -> None:
    """Validate the document-local outline tree independently of the importer."""

    wbs_by_id = {
        item["id"]: item
        for item in wbs_nodes
        if isinstance(item.get("id"), str)
    }
    ordered: list[tuple[str, dict[str, Any], str | None]] = []
    for node in wbs_nodes:
        ordered.append(("WBS node", node, node.get("parent_id")))
    for activity in activities:
        ordered.append(("Activity", activity, activity.get("parent_wbs_id")))
    ordered.sort(
        key=lambda item: (
            item[1].get("source_order")
            if isinstance(item[1].get("source_order"), int)
            else 2**63 - 1,
            str(item[1].get("id")),
        )
    )
    if not ordered:
        return

    first_level = ordered[0][1].get("outline_level")
    if not isinstance(first_level, int) or first_level < 0:
        report.errors.append("First canonical task must contain a non-negative outline_level")
        return

    for label, item, parent_ref in ordered:
        item_id = item.get("id")
        level = item.get("outline_level")
        source_order = item.get("source_order")
        if not isinstance(level, int) or level < 0:
            report.errors.append(
                f"{label} {item_id} must contain a non-negative outline_level"
            )
            continue
        if not isinstance(source_order, int) or source_order < 0:
            report.errors.append(
                f"{label} {item_id} must contain a non-negative source_order"
            )
        if level < first_level:
            report.errors.append(
                f"{label} {item_id} outline_level {level} is above root level {first_level}"
            )
            continue
        if level == first_level:
            if parent_ref is not None:
                report.errors.append(
                    f"{label} {item_id} is at root outline level {first_level} but has parent {parent_ref}"
                )
            continue
        if parent_ref is None:
            report.errors.append(
                f"{label} {item_id} at outline_level {level} requires a summary parent at level {level - 1}"
            )
            continue
        parent = wbs_by_id.get(parent_ref)
        if parent is None:
            continue
        parent_level = parent.get("outline_level")
        if parent_level != level - 1:
            report.errors.append(
                f"{label} {item_id} outline_level {level} has parent {parent_ref} at level {parent_level}; expected {level - 1}"
            )
        parent_order = parent.get("source_order")
        if isinstance(source_order, int) and (
            not isinstance(parent_order, int) or parent_order >= source_order
        ):
            report.errors.append(
                f"{label} {item_id} parent {parent_ref} must precede the child in source order"
            )


def validate_canonical_schedule(document: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()
    if document.get("schema_version") != "0.1.0":
        report.errors.append("schema_version must be '0.1.0'")

    required_arrays = (
        "wbs_nodes",
        "work_packages",
        "activities",
        "relationships",
        "calendars",
        "resources",
        "assignments",
        "baselines",
        "custom_field_definitions",
        "vendor_extensions",
    )
    for key in required_arrays:
        if not isinstance(document.get(key), list):
            report.errors.append(f"{key} must be an array")

    if report.errors:
        return report

    wbs_ids = _unique_ids(document["wbs_nodes"], "wbs_nodes", report)
    activity_ids = _unique_ids(document["activities"], "activities", report)
    relationship_ids = _unique_ids(
        document["relationships"], "relationships", report
    )
    calendar_ids = _unique_ids(document["calendars"], "calendars", report)
    resource_ids = _unique_ids(document["resources"], "resources", report)
    assignment_ids = _unique_ids(document["assignments"], "assignments", report)
    _unique_ids(document["baselines"], "baselines", report)
    _unique_ids(
        document["custom_field_definitions"], "custom_field_definitions", report
    )
    _unique_ids(document["vendor_extensions"], "vendor_extensions", report)

    del relationship_ids, assignment_ids
    all_task_ids = wbs_ids | activity_ids
    overlap = wbs_ids & activity_ids
    if overlap:
        report.errors.append(
            "Canonical task ids appear as both WBS nodes and activities: "
            f"{sorted(overlap)[:5]}"
        )

    _check_wbs_cycles(document["wbs_nodes"], report)
    _check_outline_hierarchy(document["wbs_nodes"], document["activities"], report)

    for node in document["wbs_nodes"]:
        if "milestone_source" in node and not isinstance(node["milestone_source"], bool):
            report.errors.append(
                f"WBS node {node.get('id')} milestone_source must be a boolean when present"
            )

    for activity in document["activities"]:
        parent_id = activity.get("parent_wbs_id")
        if parent_id is not None and parent_id not in wbs_ids:
            report.errors.append(
                f"Activity {activity['id']} references missing parent_wbs_id {parent_id}"
            )
        calendar_ref = activity.get("calendar_ref")
        if calendar_ref is not None and calendar_ref not in calendar_ids:
            report.warnings.append(
                f"Activity {activity['id']} references unresolved calendar {calendar_ref}"
            )

    valid_relationship_types = {"FF", "FS", "SF", "SS", "UNKNOWN"}
    for relation in document["relationships"]:
        pred = relation.get("predecessor_ref")
        succ = relation.get("successor_ref")
        if pred not in all_task_ids:
            report.errors.append(
                f"Relationship {relation['id']} references missing predecessor {pred}"
            )
        if succ not in all_task_ids:
            report.errors.append(
                f"Relationship {relation['id']} references missing successor {succ}"
            )
        if relation.get("type") not in valid_relationship_types:
            report.errors.append(
                f"Relationship {relation['id']} has invalid type {relation.get('type')!r}"
            )

    for calendar in document["calendars"]:
        base_ref = calendar.get("base_calendar_ref")
        if base_ref is not None and base_ref not in calendar_ids:
            report.warnings.append(
                f"Calendar {calendar['id']} references unresolved base calendar {base_ref}"
            )

    for assignment in document["assignments"]:
        task_ref = assignment.get("task_ref")
        resource_ref = assignment.get("resource_ref")
        if task_ref not in all_task_ids:
            report.errors.append(
                f"Assignment {assignment['id']} references missing task {task_ref}"
            )
        if resource_ref is not None and resource_ref not in resource_ids:
            report.errors.append(
                f"Assignment {assignment['id']} references missing resource {resource_ref}"
            )

    project = document.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("id"), str):
        report.errors.append("project must contain a canonical id")

    source = document.get("source")
    if not isinstance(source, dict) or source.get("format") != "MSPDI":
        report.errors.append("source.format must be MSPDI")
    else:
        hardened_profile = document.get("importer_profile") == "mspdi-import-v0.1.1"
        identity_scope = source.get("identity_scope")
        if hardened_profile and identity_scope != "document-local-v0.1":
            report.errors.append(
                "source.identity_scope must be 'document-local-v0.1' for importer v0.1.1"
            )
        if identity_scope is not None:
            if identity_scope != "document-local-v0.1":
                report.errors.append("Unsupported source.identity_scope")
            source_hash = source.get("sha256")
            expected_key = f"sha256:{source_hash}" if isinstance(source_hash, str) else None
            if source.get("document_key") != expected_key:
                report.errors.append("source.document_key must be derived from source.sha256")
            if source.get("durable_cross_snapshot_identity") != "not_implemented":
                report.errors.append(
                    "source.durable_cross_snapshot_identity must remain 'not_implemented' in v0.1"
                )

    return report
