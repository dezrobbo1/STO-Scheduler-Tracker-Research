from __future__ import annotations

from collections import Counter
from typing import Any
from xml.etree import ElementTree as ET

from .duration import duration_value
from .opaque import local_name
from .mspdi_shared import (
    MspdiImportError,
    _baseline_record,
    _boolean,
    _calendar_ref,
    _custom_field_value,
    _external_references,
    _integer,
    _number,
    _q,
    _resource_ref,
    _text,
)


def _parse_resources(container: ET.Element | None, add_extension):
    resources: list[dict[str, Any]] = []
    baselines: list[dict[str, Any]] = []
    extension_counts: Counter[str] = Counter()
    known = {
        "UID", "GUID", "ID", "Name", "Type", "IsNull", "Initials", "Group", "MaxUnits", "PeakUnits",
        "OverAllocated", "CanLevel", "Work", "RegularWork", "OvertimeWork", "ActualWork", "RemainingWork",
        "PercentWorkComplete", "StandardRate", "StandardRateFormat", "CalendarUID", "IsGeneric", "IsInactive",
        "IsEnterprise", "BookingType", "CreationDate", "IsCostResource", "IsBudget", "ExtendedAttribute",
        "Baseline", "TimephasedData",
    }
    if container is None:
        return resources, baselines, extension_counts, set()
    known_uids: set[int] = set()
    for source_order, element in enumerate(container):
        uid = _integer(element, "UID")
        if uid is None:
            raise MspdiImportError(f"Resource at source order {source_order} has no UID")
        known_uids.add(uid)
        ref = f"resource:{uid}"
        record = {
            "id": ref,
            "source_order": source_order,
            "external_references": _external_references(
                entity="Resource", uid=uid, row_id=_integer(element, "ID"), guid=_text(element, "GUID")
            ),
            "name": _text(element, "Name"),
            "source_resource_type": _integer(element, "Type"),
            "is_null_source": _boolean(element, "IsNull"),
            "initials": _text(element, "Initials"),
            "group": _text(element, "Group"),
            "calendar_ref": _calendar_ref(_integer(element, "CalendarUID")),
            "max_units": _number(element, "MaxUnits"),
            "peak_units_source": _number(element, "PeakUnits"),
            "can_level_source": _boolean(element, "CanLevel"),
            "overallocated_source": _boolean(element, "OverAllocated"),
            "work_source": duration_value(_text(element, "Work")),
            "regular_work_source": duration_value(_text(element, "RegularWork")),
            "overtime_work_source": duration_value(_text(element, "OvertimeWork")),
            "actual_work_source": duration_value(_text(element, "ActualWork")),
            "remaining_work_source": duration_value(_text(element, "RemainingWork")),
            "percent_work_complete_source": _integer(element, "PercentWorkComplete"),
            "standard_rate_source": _number(element, "StandardRate"),
            "standard_rate_format_source": _integer(element, "StandardRateFormat"),
            "booking_type_source": _integer(element, "BookingType"),
            "created_at": _text(element, "CreationDate"),
            "generic_source": _boolean(element, "IsGeneric"),
            "inactive_source": _boolean(element, "IsInactive"),
            "enterprise_source": _boolean(element, "IsEnterprise"),
            "cost_resource_source": _boolean(element, "IsCostResource"),
            "budget_source": _boolean(element, "IsBudget"),
            "custom_fields": [_custom_field_value(item) for item in element.findall(_q("ExtendedAttribute"))],
            "extension_refs": [],
        }
        for baseline_index, baseline in enumerate(element.findall(_q("Baseline"))):
            baselines.append(_baseline_record("Resource", ref, baseline, baseline_index))
        for child in element:
            name = local_name(child.tag)
            if name == "TimephasedData":
                extension_counts[name] += 1
                record["extension_refs"].append(add_extension("Resource", ref, child, "preserved-only-timephased"))
            elif name not in known:
                extension_counts[name] += 1
                record["extension_refs"].append(add_extension("Resource", ref, child, "preserved-only"))
        resources.append(record)
    return resources, baselines, extension_counts, known_uids


def _parse_assignments(
    container: ET.Element | None,
    task_ref_by_uid: dict[int, str],
    known_resource_uids: set[int],
    add_extension,
):
    assignments: list[dict[str, Any]] = []
    baselines: list[dict[str, Any]] = []
    extension_counts: Counter[str] = Counter()
    known = {
        "UID", "GUID", "TaskUID", "ResourceUID", "PercentWorkComplete", "ActualWork", "RemainingWork",
        "Work", "Start", "Finish", "Units", "Delay", "LevelingDelay", "LevelingDelayFormat", "Milestone",
        "Overallocated", "WorkContour", "Confirmed", "ResponsePending", "UpdateNeeded", "CreationDate",
        "ExtendedAttribute", "Baseline", "TimephasedData",
    }
    if container is None:
        return assignments, baselines, extension_counts
    for source_order, element in enumerate(container):
        uid = _integer(element, "UID")
        if uid is None:
            raise MspdiImportError(f"Assignment at source order {source_order} has no UID")
        task_uid = _integer(element, "TaskUID")
        resource_uid = _integer(element, "ResourceUID")
        ref = f"assignment:{uid}"
        record = {
            "id": ref,
            "source_order": source_order,
            "external_references": _external_references(entity="Assignment", uid=uid, guid=_text(element, "GUID")),
            "task_ref": task_ref_by_uid.get(task_uid) if task_uid is not None else None,
            "resource_ref": _resource_ref(resource_uid, known_resource_uids),
            "start_source": _text(element, "Start"),
            "finish_source": _text(element, "Finish"),
            "units_source": _number(element, "Units"),
            "work_source": duration_value(_text(element, "Work")),
            "actual_work_source": duration_value(_text(element, "ActualWork")),
            "remaining_work_source": duration_value(_text(element, "RemainingWork")),
            "percent_work_complete_source": _integer(element, "PercentWorkComplete"),
            "delay_tenths_minutes_source": _integer(element, "Delay"),
            "leveling_delay_tenths_minutes_source": _integer(element, "LevelingDelay"),
            "leveling_delay_format_source": _integer(element, "LevelingDelayFormat"),
            "work_contour_source": _integer(element, "WorkContour"),
            "milestone_source": _boolean(element, "Milestone"),
            "confirmed_source": _boolean(element, "Confirmed"),
            "overallocated_source": _boolean(element, "Overallocated"),
            "response_pending_source": _boolean(element, "ResponsePending"),
            "update_needed_source": _boolean(element, "UpdateNeeded"),
            "created_at": _text(element, "CreationDate"),
            "custom_fields": [_custom_field_value(item) for item in element.findall(_q("ExtendedAttribute"))],
            "extension_refs": [],
        }
        for baseline_index, baseline in enumerate(element.findall(_q("Baseline"))):
            baselines.append(_baseline_record("Assignment", ref, baseline, baseline_index))
        for child in element:
            name = local_name(child.tag)
            if name == "TimephasedData":
                extension_counts[name] += 1
                record["extension_refs"].append(add_extension("Assignment", ref, child, "preserved-only-timephased"))
            elif name not in known:
                extension_counts[name] += 1
                record["extension_refs"].append(add_extension("Assignment", ref, child, "preserved-only"))
        assignments.append(record)
    return assignments, baselines, extension_counts
