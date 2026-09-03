from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from .opaque import element_to_opaque, local_name
from .mspdi_shared import (
    MSPDI_NAMESPACE,
    MspdiImportError,
    _boolean,
    _calendar_ref,
    _child,
    _external_references,
    _integer,
    _q,
    _text,
)


def _working_times(element: ET.Element | None) -> list[dict[str, str | None]]:
    if element is None:
        return []
    result: list[dict[str, str | None]] = []
    for working_time in element.findall(_q("WorkingTime")):
        result.append({"from": _text(working_time, "FromTime"), "to": _text(working_time, "ToTime")})
    return result


def _parse_calendars(container: ET.Element | None, add_extension) -> list[dict[str, Any]]:
    calendars: list[dict[str, Any]] = []
    if container is None:
        return calendars
    known = {"UID", "GUID", "Name", "IsBaseCalendar", "IsBaselineCalendar", "BaseCalendarUID", "WeekDays", "Exceptions"}
    for source_order, element in enumerate(container):
        uid = _integer(element, "UID")
        if uid is None:
            raise MspdiImportError("Calendar UID is required")
        ref = f"calendar:{uid}"
        week_days: list[dict[str, Any]] = []
        week_days_container = _child(element, "WeekDays")
        if week_days_container is not None:
            for day in week_days_container.findall(_q("WeekDay")):
                working_times = _working_times(_child(day, "WorkingTimes"))
                week_days.append(
                    {
                        "day_type": _integer(day, "DayType"),
                        "working": _boolean(day, "DayWorking"),
                        "working_times": working_times,
                        "extensions": [
                            element_to_opaque(child, MSPDI_NAMESPACE)
                            for child in day
                            if local_name(child.tag) not in {"DayType", "DayWorking", "WorkingTimes"}
                        ],
                    }
                )
        exceptions: list[dict[str, Any]] = []
        exceptions_container = _child(element, "Exceptions")
        if exceptions_container is not None:
            for exception_index, exception in enumerate(exceptions_container.findall(_q("Exception"))):
                time_period = _child(exception, "TimePeriod")
                exceptions.append(
                    {
                        "id": f"calendar-exception:{uid}:{exception_index}",
                        "name": _text(exception, "Name"),
                        "type": _integer(exception, "Type"),
                        "working": _boolean(exception, "DayWorking"),
                        "entered_by_occurrences": _boolean(exception, "EnteredByOccurrences"),
                        "occurrences": _integer(exception, "Occurrences"),
                        "from": _text(time_period, "FromDate") if time_period is not None else None,
                        "to": _text(time_period, "ToDate") if time_period is not None else None,
                        "working_times": _working_times(_child(exception, "WorkingTimes")),
                        "raw": element_to_opaque(exception, MSPDI_NAMESPACE),
                    }
                )
        record = {
            "id": ref,
            "source_order": source_order,
            "external_references": _external_references(
                entity="Calendar", uid=uid, guid=_text(element, "GUID")
            ),
            "name": _text(element, "Name"),
            "is_base": _boolean(element, "IsBaseCalendar"),
            "is_baseline": _boolean(element, "IsBaselineCalendar"),
            "base_calendar_ref": _calendar_ref(_integer(element, "BaseCalendarUID")),
            "week_days": week_days,
            "exceptions": exceptions,
            "extension_refs": [],
        }
        for child in element:
            if local_name(child.tag) not in known:
                record["extension_refs"].append(add_extension("Calendar", ref, child, "preserved-only"))
        calendars.append(record)
    return calendars
