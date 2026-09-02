from __future__ import annotations

from collections import Counter
from typing import Any
from xml.etree import ElementTree as ET

from .duration import duration_value
from .opaque import element_to_opaque, local_name
from .mspdi_shared import (
    IMPORTER_PROFILE,
    LINK_TYPES,
    MSPDI_NAMESPACE,
    MspdiImportError,
    _baseline_record,
    _boolean,
    _calendar_ref,
    _custom_field_value,
    _external_references,
    _integer,
    _q,
    _text,
)


def _task_common(element: ET.Element, ref: str, source_order: int) -> dict[str, Any]:
    uid = _integer(element, "UID")
    row_id = _integer(element, "ID")
    guid = _text(element, "GUID")
    calendar_uid = _integer(element, "CalendarUID")
    return {
        "id": ref,
        "source_order": source_order,
        "external_references": _external_references(entity="Task", uid=uid, row_id=row_id, guid=guid),
        "name": _text(element, "Name"),
        "wbs": _text(element, "WBS"),
        "outline_number": _text(element, "OutlineNumber"),
        "outline_level": _integer(element, "OutlineLevel"),
        "active": _boolean(element, "Active"),
        "manual": _boolean(element, "Manual"),
        "is_null_source": _boolean(element, "IsNull"),
        "source_task_type": _integer(element, "Type"),
        "created_at": _text(element, "CreateDate"),
        "priority": _integer(element, "Priority"),
        "start": _text(element, "Start"),
        "finish": _text(element, "Finish"),
        "duration": duration_value(_text(element, "Duration")),
        "work": duration_value(_text(element, "Work")),
        "calendar_ref": _calendar_ref(calendar_uid),
        "estimated": _boolean(element, "Estimated"),
        "milestone_source": bool(_boolean(element, "Milestone", False)),
        "critical_source": _boolean(element, "Critical"),
        "early_start_source": _text(element, "EarlyStart"),
        "early_finish_source": _text(element, "EarlyFinish"),
        "late_start_source": _text(element, "LateStart"),
        "late_finish_source": _text(element, "LateFinish"),
        "free_slack_tenths_minutes_source": _integer(element, "FreeSlack"),
        "total_slack_tenths_minutes_source": _integer(element, "TotalSlack"),
        "percent_complete_source": _integer(element, "PercentComplete"),
        "percent_work_complete_source": _integer(element, "PercentWorkComplete"),
        "physical_percent_complete_source": _integer(element, "PhysicalPercentComplete"),
        "actual_start_source": _text(element, "ActualStart"),
        "actual_finish_source": _text(element, "ActualFinish"),
        "actual_duration_source": duration_value(_text(element, "ActualDuration")),
        "actual_work_source": duration_value(_text(element, "ActualWork")),
        "remaining_duration_source": duration_value(_text(element, "RemainingDuration")),
        "remaining_work_source": duration_value(_text(element, "RemainingWork")),
        "constraint_type_source": _integer(element, "ConstraintType"),
        "constraint_date_source": _text(element, "ConstraintDate"),
        "deadline_source": _text(element, "Deadline"),
        "notes": _text(element, "Notes"),
        "custom_fields": [_custom_field_value(item) for item in element.findall(_q("ExtendedAttribute"))],
        "extension_refs": [],
    }


def _parse_tasks(container: ET.Element | None, add_extension):
    if container is None:
        return [], [], [], [], {}, Counter()
    elements = list(container)
    task_ref_by_uid: dict[int, str] = {}
    summary_by_level: dict[int, str] = {}
    root_outline_level: int | None = None
    wbs_nodes: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    baselines: list[dict[str, Any]] = []
    task_extensions: Counter[str] = Counter()
    source_task_elements: list[tuple[ET.Element, str]] = []

    common_known = {
        "UID", "GUID", "ID", "Name", "Active", "Manual", "Type", "IsNull", "CreateDate",
        "WBS", "OutlineNumber", "OutlineLevel", "Priority", "Start", "Finish", "Duration",
        "Work", "CalendarUID", "Estimated", "Critical", "EarlyStart", "EarlyFinish", "LateStart",
        "LateFinish", "FreeSlack", "TotalSlack", "PercentComplete", "PercentWorkComplete",
        "PhysicalPercentComplete", "ActualStart", "ActualFinish", "ActualDuration", "ActualWork",
        "RemainingDuration", "RemainingWork", "ConstraintType", "ConstraintDate", "Deadline",
        "Notes", "Summary", "Milestone", "ExtendedAttribute", "PredecessorLink", "Baseline",
        "TimephasedData",
    }

    for source_order, element in enumerate(elements):
        uid = _integer(element, "UID")
        if uid is None:
            raise MspdiImportError(f"Task at source order {source_order} has no UID")
        ref = f"task:{uid}"
        if uid in task_ref_by_uid:
            raise MspdiImportError(f"Duplicate task UID {uid}")
        task_ref_by_uid[uid] = ref
        source_task_elements.append((element, ref))

        level = _integer(element, "OutlineLevel")
        if level is None:
            raise MspdiImportError(f"Task UID {uid} has no OutlineLevel")
        if level < 0:
            raise MspdiImportError(f"Task UID {uid} has negative OutlineLevel {level}")
        if root_outline_level is None:
            root_outline_level = level
        elif level < root_outline_level:
            raise MspdiImportError(
                f"Task UID {uid} OutlineLevel {level} is above root level {root_outline_level}"
            )

        for old_level in [key for key in summary_by_level if key >= level]:
            del summary_by_level[old_level]

        parent_ref: str | None = None
        if level > root_outline_level:
            parent_ref = summary_by_level.get(level - 1)
            if parent_ref is None:
                raise MspdiImportError(
                    f"Task UID {uid} at OutlineLevel {level} has no preceding summary parent at level {level - 1}"
                )

        is_summary = bool(_boolean(element, "Summary", False))
        common = _task_common(element, ref, source_order)
        common["source_uid"] = uid
        if is_summary:
            record = {
                **common,
                "parent_id": parent_ref,
                "project_summary": level == 0,
            }
            wbs_nodes.append(record)
            summary_by_level[level] = ref
        else:
            record = {
                **common,
                "parent_wbs_id": parent_ref,
                "milestone": common["milestone_source"],
            }
            activities.append(record)

        owner_kind = "WBSNode" if is_summary else "Activity"
        owner_record = wbs_nodes[-1] if is_summary else activities[-1]
        for baseline_index, baseline in enumerate(element.findall(_q("Baseline"))):
            baselines.append(_baseline_record(owner_kind, ref, baseline, baseline_index))
        for child in element:
            name = local_name(child.tag)
            if name == "TimephasedData":
                task_extensions[name] += 1
                owner_record["extension_refs"].append(add_extension(owner_kind, ref, child, "preserved-only-timephased"))
            elif name not in common_known:
                task_extensions[name] += 1
                owner_record["extension_refs"].append(add_extension(owner_kind, ref, child, "preserved-only"))

    relationships: list[dict[str, Any]] = []
    for successor_element, successor_ref in source_task_elements:
        successor_uid = _integer(successor_element, "UID")
        for relation_index, link in enumerate(successor_element.findall(_q("PredecessorLink"))):
            predecessor_uid = _integer(link, "PredecessorUID")
            predecessor_ref = task_ref_by_uid.get(predecessor_uid) if predecessor_uid is not None else None
            raw_type = _integer(link, "Type")
            raw_lag = _integer(link, "LinkLag", 0)
            relation_id = f"relationship:{successor_uid}:{relation_index}"
            relationships.append(
                {
                    "id": relation_id,
                    "source_order": len(relationships),
                    "predecessor_ref": predecessor_ref,
                    "successor_ref": successor_ref,
                    "type": LINK_TYPES.get(raw_type, "UNKNOWN"),
                    "source_type_code": raw_type,
                    "lag_tenths_minutes": raw_lag,
                    "lag_seconds": raw_lag * 6 if raw_lag is not None else None,
                    "lag_format_source": _integer(link, "LagFormat"),
                    "cross_project": _boolean(link, "CrossProject", False),
                    "cross_project_name": _text(link, "CrossProjectName"),
                    "extensions": [
                        element_to_opaque(child, MSPDI_NAMESPACE)
                        for child in link
                        if local_name(child.tag)
                        not in {"PredecessorUID", "Type", "CrossProject", "CrossProjectName", "LinkLag", "LagFormat"}
                    ],
                }
            )

    return wbs_nodes, activities, relationships, baselines, task_ref_by_uid, task_extensions
