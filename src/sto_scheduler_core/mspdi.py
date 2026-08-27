from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .mspdi_calendars import _parse_calendars
from .mspdi_resources import _parse_assignments, _parse_resources
from .mspdi_shared import (
    IMPORTER_PROFILE,
    MSPDI_NAMESPACE,
    SCHEMA_VERSION,
    MspdiImportError,
    _boolean,
    _calendar_ref,
    _child,
    _integer,
    _parse_custom_field_definitions,
    _project_identity,
    _text,
)
from .mspdi_tasks import _parse_tasks
from .opaque import element_to_opaque, local_name, split_tag
from .provenance import file_sha256
from .validation import validate_canonical_schedule


def _compatibility_profile() -> dict[str, Any]:
    return {
        "profile": IMPORTER_PROFILE,
        "claim_boundary": "Import mapping classification only; not a Microsoft Project semantic compatibility claim.",
        "semantics": {
            "project_identity": "Full",
            "task_uid_guid_id": "Full",
            "wbs_outline_hierarchy": "Mapped",
            "summary_tasks": "Mapped",
            "leaf_activities": "Mapped",
            "relationships_and_raw_lag": "Mapped",
            "calendars_and_exceptions": "Mapped",
            "resources": "Mapped",
            "assignments": "Mapped",
            "custom_field_definitions_and_values": "Mapped",
            "source_early_late_dates_and_slack": "Read-only",
            "source_actual_and_remaining_fields": "Read-only",
            "baselines": "Preserved-only",
            "timephased_data": "Preserved-only",
            "project_formulas": "Preserved-only",
            "unmodelled_mspdi_fields": "Preserved-only",
            "native_project_recalculation": "Unsupported until executed evidence exists",
        },
    }


def import_mspdi(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    source_hash = file_sha256(source_path)
    try:
        tree = ET.parse(source_path)
    except (ET.ParseError, OSError) as exc:
        raise MspdiImportError(f"Unable to parse MSPDI file {source_path}: {exc}") from exc
    root = tree.getroot()
    namespace, root_name = split_tag(root.tag)
    if root_name != "Project" or namespace != MSPDI_NAMESPACE:
        raise MspdiImportError(
            f"Expected MSPDI Project root in {MSPDI_NAMESPACE!r}; got root={root_name!r}, namespace={namespace!r}"
        )

    vendor_extensions: list[dict[str, Any]] = []

    def add_extension(owner_kind: str, owner_ref: str, element: ET.Element, classification: str) -> str:
        extension_id = f"vendor-extension:{len(vendor_extensions):06d}"
        vendor_extensions.append(
            {
                "id": extension_id,
                "source_order": len(vendor_extensions),
                "owner_kind": owner_kind,
                "owner_ref": owner_ref,
                "classification": classification,
                "payload": element_to_opaque(element, MSPDI_NAMESPACE),
            }
        )
        return extension_id

    project_id, project_refs = _project_identity(root, source_hash)
    project_calendar_uid = _integer(root, "CalendarUID")
    project = {
        "id": project_id,
        "external_references": project_refs,
        "name": _text(root, "Name"),
        "title": _text(root, "Title"),
        "created_at": _text(root, "CreationDate"),
        "last_saved_at": _text(root, "LastSaved"),
        "schedule_from_start": _boolean(root, "ScheduleFromStart"),
        "start": _text(root, "StartDate"),
        "finish": _text(root, "FinishDate"),
        "status_date": _text(root, "StatusDate"),
        "calendar_ref": _calendar_ref(project_calendar_uid),
        "baseline_calendar_name_source": _text(root, "BaselineCalendar"),
        "default_start_time": _text(root, "DefaultStartTime"),
        "default_finish_time": _text(root, "DefaultFinishTime"),
        "minutes_per_day": _integer(root, "MinutesPerDay"),
        "minutes_per_week": _integer(root, "MinutesPerWeek"),
        "days_per_month": _integer(root, "DaysPerMonth"),
        "critical_slack_limit_source": _integer(root, "CriticalSlackLimit"),
        "multiple_critical_paths_source": _boolean(root, "MultipleCriticalPaths"),
        "splits_in_progress_tasks_source": _boolean(root, "SplitsInProgressTasks"),
        "extension_refs": [],
    }
    root_known = {
        "SaveVersion", "BuildNumber", "Name", "GUID", "Title", "CreationDate", "LastSaved",
        "ScheduleFromStart", "StartDate", "FinishDate", "StatusDate", "CalendarUID", "BaselineCalendar",
        "DefaultStartTime", "DefaultFinishTime", "MinutesPerDay", "MinutesPerWeek", "DaysPerMonth",
        "CriticalSlackLimit", "MultipleCriticalPaths", "SplitsInProgressTasks", "ExtendedAttributes",
        "Calendars", "Tasks", "Resources", "Assignments",
    }
    project_extension_counts: Counter[str] = Counter()
    for child in root:
        name = local_name(child.tag)
        if name not in root_known:
            project_extension_counts[name] += 1
            project["extension_refs"].append(add_extension("Project", project_id, child, "preserved-only"))

    calendars = _parse_calendars(_child(root, "Calendars"), add_extension)
    wbs_nodes, activities, relationships, task_baselines, task_ref_by_uid, task_extension_counts = _parse_tasks(
        _child(root, "Tasks"), add_extension
    )
    resources, resource_baselines, resource_extension_counts, known_resource_uids = _parse_resources(
        _child(root, "Resources"), add_extension
    )
    assignments, assignment_baselines, assignment_extension_counts = _parse_assignments(
        _child(root, "Assignments"), task_ref_by_uid, known_resource_uids, add_extension
    )
    custom_field_definitions = _parse_custom_field_definitions(_child(root, "ExtendedAttributes"))

    relationship_type_counts = Counter(item["type"] for item in relationships)
    activity_milestones = sum(1 for item in activities if item.get("milestone"))
    task_container = _child(root, "Tasks")
    summary_milestones = sum(
        1
        for element in (list(task_container) if task_container is not None else [])
        if _boolean(element, "Summary", False) and _boolean(element, "Milestone", False)
    )
    inventory = {
        "tasks": len(wbs_nodes) + len(activities),
        "summary_tasks": len(wbs_nodes),
        "leaf_activities": len(activities),
        "milestones": activity_milestones + summary_milestones,
        "activity_milestones": activity_milestones,
        "summary_milestones": summary_milestones,
        "relationships": len(relationships),
        "relationship_types": dict(sorted(relationship_type_counts.items())),
        "calendars": len(calendars),
        "resources": len(resources),
        "assignments": len(assignments),
        "baselines": len(task_baselines) + len(resource_baselines) + len(assignment_baselines),
        "custom_field_definitions": len(custom_field_definitions),
        "vendor_extensions": len(vendor_extensions),
        "preserved_extension_element_counts": dict(
            sorted(
                (project_extension_counts + task_extension_counts + resource_extension_counts + assignment_extension_counts).items()
            )
        ),
    }

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "importer_profile": IMPORTER_PROFILE,
        "source": {
            "system": "MicrosoftProject",
            "format": "MSPDI",
            "namespace": namespace,
            "sha256": source_hash,
            "byte_length": source_path.stat().st_size,
            "document_name": _text(root, "Name"),
            "save_version": _integer(root, "SaveVersion"),
            "build_number": _text(root, "BuildNumber"),
        },
        "project": project,
        "wbs_nodes": wbs_nodes,
        "work_packages": [],
        "activities": activities,
        "relationships": relationships,
        "calendars": calendars,
        "resources": resources,
        "assignments": assignments,
        "baselines": task_baselines + resource_baselines + assignment_baselines,
        "custom_field_definitions": custom_field_definitions,
        "vendor_extensions": vendor_extensions,
        "source_inventory": inventory,
        "compatibility": _compatibility_profile(),
    }
    validation = validate_canonical_schedule(document)
    document["import_validation"] = validation.as_dict()
    if not validation.valid:
        raise MspdiImportError("Canonical validation failed: " + "; ".join(validation.errors))
    return document


def inventory_mspdi(path: str | Path) -> dict[str, Any]:
    document = import_mspdi(path)
    return {
        "experiment_profile": IMPORTER_PROFILE,
        "source": {
            "format": document["source"]["format"],
            "namespace": document["source"]["namespace"],
            "sha256": document["source"]["sha256"],
            "byte_length": document["source"]["byte_length"],
        },
        "schema_version": document["schema_version"],
        "counts": document["source_inventory"],
        "validation": document["import_validation"],
        "native_project_validation": "not_executed",
    }
