#!/usr/bin/env python3
"""Analyze the predeclared V2 RC01 assignment-envelope Project return.

This is evidence tooling only.  It validates every experiment-defining input
before reading the native output fields and can authorize only a later,
diagnostic-only BOILER counterfactual.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Mapping
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence import p1_g2_rc01_assignment_native_v2_generate as generate

NS = {"p": generate.URI}
SCHEMA = "sto-p1-g2-rc01-assignment-envelope-native-v2"
DATE_FIELDS = ("Start", "Finish", "EarlyStart", "EarlyFinish")
NATIVE_BUILD = re.compile(r"^16\.0\.\d+\.\d+$")
GUID = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")

# Input fields absent in V1 that Project inserted on the genuine V1 save.
# These values affect scheduling and are not unconstrained output fields.
PROJECT_NORMALIZED_OPTIONS = {
    "HonorConstraints": "0", "TaskUpdatesResource": "1",
    "SplitsInProgressTasks": "1", "MoveRemainingStartsForward": "0",
    "MoveRemainingStartsBack": "0", "MoveCompletedEndsForward": "0",
    "MoveCompletedEndsBack": "0", "KeepTaskOnNearestWorkingTimeWhenMadeAutoScheduled": "0",
    "AutoAddNewResourcesAndTasks": "1", "NewTaskStartDate": "0",
    "UpdateManuallyScheduledTasksWhenEditingLinks": "1",
    "WeekStartDay": "1", "ActualsInSync": "0", "DurationFormat": "7",
}
PROJECT_METADATA = {
    "CreationDate", "CurrentDate", "LastSaved", "ExtendedCreationDate",
    "AgileMode", "DefaultTaskEVMethod", "CurrencyCode", "CurrencySymbol",
    "CurrencySymbolPosition", "CurrencyDigits", "EditableActualCosts", "FYStartDate",
    "FiscalYearStart", "SprintLength", "BaselineForEarnedValue",
    "MicrosoftProjectServerURL", "RemoveFileProperties", "WorkFormat",
    "DefaultFixedCostAccrual", "DefaultOvertimeRate", "InsertedProjectsLikeSummary",
    "AdminProject", "SpreadActualCost", "SpreadPercentComplete", "DefaultStandardRate",
}
PROJECT_SAVE_CONTAINERS = {
    "Views", "Filters", "Groups", "Tables", "Maps", "Reports", "Drawings",
    "DataLinks", "VBAProjects", "OutlineCodes", "WBSMasks",
    "ExtendedAttributes", "BoardColumns", "Sprints",
}
PROJECT_EMPTY_CONTAINERS = {
    "Maps", "Reports", "Drawings", "DataLinks", "VBAProjects",
    "OutlineCodes", "WBSMasks", "ExtendedAttributes",
}
PROJECT_METADATA_VALUES = {
    "AdminProject": "0", "AgileMode": "2", "BaselineForEarnedValue": "0",
    "CurrencyCode": "AUD", "CurrencyDigits": "2", "CurrencySymbol": "$",
    "CurrencySymbolPosition": "0", "DefaultFixedCostAccrual": "3",
    "DefaultOvertimeRate": "0", "DefaultStandardRate": "0",
    "DefaultTaskEVMethod": "0", "EditableActualCosts": "0",
    "ExtendedCreationDate": "1984-01-01T00:00:00", "FYStartDate": "1",
    "FiscalYearStart": "0", "InsertedProjectsLikeSummary": "0",
    "MicrosoftProjectServerURL": "1", "RemoveFileProperties": "0",
    "SpreadActualCost": "0", "SpreadPercentComplete": "0",
    "SprintLength": "2", "WorkFormat": "2",
}
TASK_NATIVE_OUTPUTS = {
    "Duration", "RemainingDuration", "Finish", "EarlyStart", "EarlyFinish",
    "LateStart", "LateFinish", "FreeSlack", "TotalSlack", "Critical",
}
TASK_SAVE_FIELDS = {
    "CommitmentType", "ManualStart", "ManualFinish", "ManualDuration",
    "WorkVariance", "BCWS", "Cost", "CV", "FixedCost", "StartVariance",
    "FinishVariance", "RemainingOvertimeWork", "ResumeValid", "ExternalTask",
    "OvertimeWork", "ActualOvertimeCost", "OvertimeCost", "ActualCost",
    "FreeformDurationFormat", "ActualOvertimeWork", "FixedCostAccrual",
    "SprintUID", "IsSubprojectReadOnly", "ACWP", "EarnedValueMethod",
    "BCWP", "IsSubproject", "DisplayAsSummary", "NextAvailableSprintOrderingID",
    "RemainingCost", "RemainingOvertimeCost", "FinishSlack", "StartSlack", "BoardStatusColumnOrderingID",
    "NextAvailableBoardStatusColumnOrderingID", "SprintColumnOrderingID",
    "BoardColumnUID",
}
RESOURCE_SAVE_FIELDS = {
    "WorkVariance", "BCWS", "Cost", "CV", "StandardRate", "SV",
    "CreationDate", "ACWP", "BCWP", "CostPerUse", "OvertimeRateFormat",
    "RemainingOvertimeWork", "RemainingOvertimeCost", "CostVariance",
    "OvertimeWork", "ActualOvertimeCost", "OvertimeCost", "BookingType",
    "OvertimeRate", "ActualCost", "ActualOvertimeWork", "RemainingCost",
    "StandardRateFormat", "AccrueAt",
}
ASSIGNMENT_SAVE_FIELDS = {
    "WorkVariance", "BCWS", "Cost", "CV", "LinkedFields", "StartVariance",
    "VAC", "FinishVariance", "ACWP", "BCWP", "HasFixedRateUnits",
    "FixedMaterial", "RemainingOvertimeWork", "RemainingOvertimeCost",
    "CostVariance", "OvertimeWork", "ActualOvertimeCost", "BudgetWork",
    "OvertimeCost", "BookingType", "ActualCost", "ActualOvertimeWork",
    "RemainingCost", "CostRateTable", "BudgetCost", "RateScale",
}


class NativeEvidenceError(ValueError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _text(parent: ET.Element, field: str) -> str | None:
    return parent.findtext(f"p:{field}", default=None, namespaces=NS)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeEvidenceError(message)


def _datetime(value: str | None, where: str) -> datetime:
    try:
        result = datetime.fromisoformat(value or "")
    except ValueError as error:
        raise NativeEvidenceError(f"missing or invalid native date: {where}") from error
    if result.tzinfo is not None:
        raise NativeEvidenceError(f"timezone-bearing native date is outside contract: {where}")
    return result


def _decimal(value: str | None, where: str) -> Decimal:
    try:
        return Decimal(value or "")
    except InvalidOperation as error:
        raise NativeEvidenceError(f"missing or invalid numeric input: {where}") from error


def _named(container: ET.Element | None, kind: str) -> dict[str, ET.Element]:
    _require(container is not None, f"native return is missing {kind} container")
    rows: dict[str, ET.Element] = {}
    for row in list(container):
        name = _text(row, "Name")
        if name:
            _require(name not in rows, f"native return duplicates {kind} name {name}")
            rows[name] = row
    return rows


def _uid_rows(container: ET.Element | None, kind: str) -> dict[int, ET.Element]:
    _require(container is not None, f"native return is missing {kind} container")
    rows = {}
    for row in container:
        uid = _text(row, "UID")
        _require(uid is not None and uid.isdigit(), f"{kind} UID is invalid")
        key = int(uid)
        _require(key not in rows, f"duplicate {kind} UID {key}")
        rows[key] = row
    return rows


def _guard_extra(row: ET.Element, expected: ET.Element, allowed: set[str], where: str) -> None:
    declared = {item.tag for item in expected}
    for child in row:
        name = child.tag.rsplit("}", 1)[-1]
        _require(child.tag in declared or name in allowed,
                 f"unknown scheduling/identity field at {where}.{name}")


def _validate_save_delta(row: ET.Element, expected: ET.Element,
                         outputs: set[str], additions: set[str], where: str) -> None:
    def signature(item: ET.Element) -> object:
        return (item.tag, (item.text or "").strip(), tuple(sorted(item.attrib.items())),
                tuple(signature(child) for child in item))

    _guard_extra(row, expected, additions, where)
    for item in expected:
        name = item.tag.rsplit("}", 1)[-1]
        if name in outputs:
            continue
        found = row.find(item.tag)
        _require(found is not None and signature(found) == signature(item),
                 f"semantic input changed: {where}.{name}")


def _calendar_signature(row: ET.Element) -> tuple[tuple[int, bool, tuple[tuple[str, str], ...]], ...]:
    result: list[tuple[int, bool, tuple[tuple[str, str], ...]]] = []
    for weekday in row.findall("p:WeekDays/p:WeekDay", NS):
        day_text = _text(weekday, "DayType")
        _require(day_text is not None and day_text.isdigit(), "calendar has invalid weekday identity")
        intervals = tuple(
            (_text(item, "FromTime") or "", _text(item, "ToTime") or "")
            for item in weekday.findall("p:WorkingTimes/p:WorkingTime", NS)
        )
        working = _text(weekday, "DayWorking")
        _require(working in ("0", "1"), "calendar has invalid working-day flag")
        result.append((int(day_text), working == "1", intervals))
    return tuple(result)


def _expected_calendar_signature(intervals: tuple[tuple[str, str], ...]):
    return tuple(
        (day, 2 <= day <= 6, intervals if 2 <= day <= 6 else ())
        for day in range(1, 8)
    )


def parse_and_validate(payload: bytes) -> dict[str, object]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise NativeEvidenceError(f"native return is not valid MSPDI XML: {error}") from error
    _require(root.tag == generate.q("Project"), "native return is not an MSPDI Project")
    original = ET.fromstring(generate.build_fixture())

    expected_project = {
        "Name": generate.PROJECT_NAME,
        "ScheduleFromStart": "1",
        "StartDate": generate.PROJECT_START,
        "CalendarUID": "1",
        "DefaultStartTime": "08:00:00",
        "DefaultFinishTime": "17:00:00",
        "MinutesPerDay": "480",
        "MinutesPerWeek": "2400",
        "DaysPerMonth": "20",
        "DefaultTaskType": "0",
        "NewTasksEffortDriven": "0",
        "NewTasksEstimated": "0",
        "NewTasksAreManual": "0",
    }
    for field, expected in expected_project.items():
        _require(_text(root, field) == expected, f"project input changed: {field}")
    _require(GUID.fullmatch(_text(root, "GUID") or "") is not None,
             "project GUID normalization is invalid")
    _require(_text(root, "AutoLink") is not None or _text(root, "Autolink") is not None,
             "project AutoLink missing")
    for spelling in ("AutoLink", "Autolink"):
        _require(_text(root, spelling) in (None, "0"),
                 f"project {spelling} changed")
    for key, value in PROJECT_NORMALIZED_OPTIONS.items():
        _require(_text(root, key) in (None, value), f"project scheduling option changed: {key}")
    for key, value in PROJECT_METADATA_VALUES.items():
        _require(_text(root, key) in (None, value),
                 f"unknown Project save normalization: {key}")
    for key in ("CreationDate", "CurrentDate", "LastSaved"):
        value = _text(root, key)
        if value is not None:
            _datetime(value, f"project.{key}")
    _guard_extra(root, original, PROJECT_METADATA | PROJECT_SAVE_CONTAINERS
                 | set(PROJECT_NORMALIZED_OPTIONS) | {"Autolink"}, "project")
    for field in PROJECT_EMPTY_CONTAINERS:
        node = root.find(f"p:{field}", NS)
        _require(node is None or len(node) == 0,
                 f"unexpected content in native {field}")
    for item in original:
        field = item.tag.rsplit("}", 1)[-1]
        if field in {"GUID", "BuildNumber", "FinishDate", "AutoLink", "Calendars",
                     "Tasks", "Resources", "Assignments"}:
            continue
        _require(_text(root, field) == item.text,
                 f"project input changed: {field}")

    calendars = _uid_rows(root.find("p:Calendars", NS), "calendar")
    _require(
        set(calendars) in (set(generate.CALENDARS), set(generate.CALENDARS) | {6}),
        "calendar UID set changed",
    )
    if 6 in calendars:
        extra = calendars[6]
        for field, value in {"UID": "6", "Name": "Standard", "IsBaseCalendar": "1",
                             "BaseCalendarUID": "0"}.items():
            _require(_text(extra, field) == value, f"unexpected default calendar: {field}")
        _require(not any(_text(row, "ResourceUID") == "6" for row in root.findall(
            "p:Assignments/p:Assignment", NS)), "default calendar participates in assignments")
    for uid, spec in generate.CALENDARS.items():
        name = str(spec["name"])
        row = calendars[uid]
        expected_row = original.find(f"p:Calendars/p:Calendar[p:UID='{uid}']", NS)
        _require(expected_row is not None, "generator calendar missing")
        _validate_save_delta(row, expected_row,
                             {"Name", "WeekDays"} if uid != 1 else set(), set(), name)
        _require(_text(row, "Name") in ({name, "Unassigned"} if uid != 1 else {name}),
                 f"calendar display name normalization outside V1: {uid}")
        expected = {
            "UID": str(uid),
            "GUID": str(spec["guid"]),
            "IsBaseCalendar": "1" if uid == 1 else "0",
            "BaseCalendarUID": str(spec["base"]),
        }
        for field, value in expected.items():
            _require(_text(row, field) == value, f"calendar input changed: {name}.{field}")
        observed_week = _calendar_signature(row)
        expected_week = _expected_calendar_signature(spec["intervals"])
        _require(
            observed_week == expected_week or
            (uid != 1 and observed_week == expected_week[1:6]),
            f"calendar working intervals changed: {name}",
        )
        _require(
            not row.findall("p:Exceptions/p:Exception", NS),
            f"calendar exceptions changed: {name}",
        )

    task_rows = _named(root.find("p:Tasks", NS), "task")
    summary = _uid_rows(root.find("p:Tasks", NS), "task")
    _require(set(summary) in ({1, 2, 3, 4}, {0, 1, 2, 3, 4}),
             "task UID set changed")
    if 0 in summary:
        reference_task = original.find("p:Tasks/p:Task", NS)
        _require(reference_task is not None, "generator task missing")
        _guard_extra(summary[0], reference_task,
                     TASK_SAVE_FIELDS | TASK_NATIVE_OUTPUTS | {"CalendarUID"},
                     "native summary")
        _require(_text(summary[0], "Summary") == "1" and not summary[0].findall(
            "p:PredecessorLink", NS), "unexpected native summary task")
        _require(_text(summary[0], "Name") in (generate.EXPERIMENT_ID,
                  generate.PROJECT_NAME), "unexpected native summary identity")
        for field, value in {
            "UID": "0", "ID": "0", "Manual": "0", "Active": "1",
            "Type": "1", "CalendarUID": "-1", "PercentComplete": "0",
            "PercentWorkComplete": "0", "ActualWork": "PT0H0M0S",
            "ConstraintType": "0", "LevelingDelay": "0",
        }.items():
            _require(_text(summary[0], field) == value,
                     f"unexpected native summary input: {field}")
        _require(not any(_text(a, "TaskUID") == "0" for a in root.findall(
            "p:Assignments/p:Assignment", NS)), "summary task participates in assignments")
        del task_rows[_text(summary[0], "Name")]
    _require(
        set(task_rows) == {f"RC01-CASE-{case}" for case in generate.TASKS},
        "task identity set changed",
    )
    tasks: dict[str, dict[str, object]] = {}
    for case, spec in generate.TASKS.items():
        name = f"RC01-CASE-{case}"
        _require(name in task_rows, f"task identity changed or missing: {name}")
        row = task_rows[name]
        expected_row = original.find(f"p:Tasks/p:Task[p:UID='{spec['uid']}']", NS)
        _require(expected_row is not None, "generator task missing")
        _validate_save_delta(row, expected_row,
                             TASK_NATIVE_OUTPUTS | {"LevelingDelayFormat", "CalendarUID"},
                             TASK_SAVE_FIELDS | {"CalendarUID"}, name)
        exact = {
            "UID": str(spec["uid"]),
            "GUID": str(spec["guid"]),
            "ID": str(spec["uid"]),
            "Active": "1",
            "Manual": "0",
            "Type": "0",
            "DurationFormat": "7",
            "Work": str(spec["work"]),
            "EffortDriven": "0",
            "Estimated": "0",
            "Milestone": "0",
            "Summary": "0",
            "PercentComplete": "0",
            "PercentWorkComplete": "0",
            "ActualDuration": "PT0H0M0S",
            "ActualWork": "PT0H0M0S",
            "RemainingWork": str(spec["work"]),
            "ConstraintType": "0",
            "LevelAssignments": "0",
            "LevelingCanSplit": "0",
            "LevelingDelay": "0",
            "IgnoreResourceCalendar": "0",
        }
        labels = {
            "GUID": "task identity",
            "UID": "task identity",
            "ID": "task identity",
            "Type": "task type",
            "EffortDriven": "effort driven",
            "IgnoreResourceCalendar": "ignore resource calendar",
            "Duration": "duration",
            "Start": "start",
        }
        for field, expected in exact.items():
            _require(
                _text(row, field) == expected,
                f"{labels.get(field, 'task input')} changed: {name}.{field}",
            )
        _require(_text(row, "CalendarUID") in (None, "-1"), f"task calendar changed: {name}")
        _require(_text(row, "LevelingDelayFormat") in ("7", "8"),
                 f"levelling format changed: {name}")
        _require(not row.findall("p:PredecessorLink", NS), f"topology changed: {name}")
        start = _datetime(_text(row, "Start"), f"{name}.Start")
        _require(start == datetime.fromisoformat(generate.PROJECT_START), f"start changed: {name}")
        tasks[case] = {
            "uid": int(spec["uid"]),
            "type": _text(row, "Type"),
            "effort_driven": _text(row, "EffortDriven"),
            "ignore_resource_calendar": _text(row, "IgnoreResourceCalendar"),
        }

    resource_rows = _named(root.find("p:Resources", NS), "resource")
    all_resources = _uid_rows(root.find("p:Resources", NS), "resource")
    _require(set(all_resources) in ({1, 2, 3, 4}, {0, 1, 2, 3, 4}),
             "resource UID set changed")
    if 0 in all_resources:
        _require(_text(all_resources[0], "ID") == "0" and
                 _text(all_resources[0], "CalendarUID") == "7" and
                 _text(all_resources[0], "CanLevel") == "1" and
                 not any(_text(a, "ResourceUID") == "0" for a in root.findall(
                     "p:Assignments/p:Assignment", NS)),
                 "unexpected native null resource")
    _require(
        set(resource_rows) == {str(spec["name"]) for spec in generate.RESOURCES.values()},
        "resource identity set changed",
    )
    resources: dict[int, dict[str, object]] = {}
    for uid, spec in generate.RESOURCES.items():
        name = str(spec["name"])
        _require(name in resource_rows, f"resource identity changed or missing: {name}")
        row = resource_rows[name]
        expected_row = original.find(f"p:Resources/p:Resource[p:UID='{uid}']", NS)
        _require(expected_row is not None, "generator resource missing")
        _validate_save_delta(row, expected_row,
                             {"GUID", "MaxUnits", "PeakUnits", "OverAllocated"},
                             RESOURCE_SAVE_FIELDS, name)
        exact = {
            "UID": str(uid),
            "ID": str(uid),
            "Type": "1",
            "MaxUnits": Decimal("1"),
            "CanLevel": "0",
            "CalendarUID": str(spec["calendar"]),
            "IsInactive": "0",
        }
        _require(_text(row, "GUID") in (str(spec["guid"]),
                  str(generate.CALENDARS[spec["calendar"]]["guid"])),
                 f"resource GUID normalization outside V1: {name}")
        for field, expected in exact.items():
            if field == "MaxUnits":
                actual: object = _decimal(_text(row, field), f"{name}.{field}")
            else:
                actual = _text(row, field)
            label = "resource calendar" if field == "CalendarUID" else "resource identity" if field in {"UID", "GUID", "ID"} else "resource input"
            _require(actual == expected, f"{label} changed: {name}.{field}")
        resources[uid] = {"name": name, "calendar_uid": int(spec["calendar"])}

    assignments_element = root.find("p:Assignments", NS)
    _require(assignments_element is not None, "native return is missing assignments")
    assignment_rows = list(assignments_element)
    order = [_text(row, "UID") for row in assignment_rows]
    expected_order = [str(uid) for uid in generate.ASSIGNMENT_ORDER]
    _require(order == expected_order, "assignment order changed")
    assignments: dict[int, dict[str, object]] = {}
    specs = {int(row["uid"]): row for row in generate.ASSIGNMENTS}
    for row in assignment_rows:
        uid_text = _text(row, "UID")
        _require(uid_text is not None and uid_text.isdigit(), "assignment identity is invalid")
        uid = int(uid_text)
        _require(uid in specs, f"assignment identity changed: {uid}")
        spec = specs[uid]
        expected_row = original.find(f"p:Assignments/p:Assignment[p:UID='{uid}']", NS)
        _require(expected_row is not None, "generator assignment missing")
        _validate_save_delta(row, expected_row, {"Start", "Finish", "RegularWork"},
                             ASSIGNMENT_SAVE_FIELDS | {"RegularWork", "TimephasedData"},
                             f"assignment {uid}")
        _require(_text(row, "RegularWork") in (None, generate.ASSIGNMENT_WORK),
                 f"assignment regular work changed: {uid}")
        exact_text = {
            "GUID": str(spec["guid"]),
            "TaskUID": str(generate.TASKS[spec["case"]]["uid"]),
            "ResourceUID": str(spec["resource"]),
            "Work": generate.ASSIGNMENT_WORK,
            "ActualWork": "PT0H0M0S",
            "RemainingWork": generate.ASSIGNMENT_WORK,
            "PercentWorkComplete": "0",
            "Delay": "0",
            "LevelingDelay": "0",
        }
        for field, expected in exact_text.items():
            label = (
                "assignment identity" if field in {"GUID", "TaskUID", "ResourceUID"}
                else "assignment work" if field in {"Work", "ActualWork", "RemainingWork"}
                else "assignment input"
            )
            _require(_text(row, field) == expected, f"{label} changed: {uid}.{field}")
        _require(
            _decimal(_text(row, "Units"), f"assignment {uid}.Units")
            == Decimal(generate.ASSIGNMENT_UNITS),
            f"assignment units changed: {uid}.Units",
        )
        assignments[uid] = {
            "uid": uid,
            "case": str(spec["case"]),
            "role": str(spec["role"]),
            "resource_uid": int(spec["resource"]),
            "work": _text(row, "Work"),
            "units": str(_decimal(_text(row, "Units"), f"assignment {uid}.Units")),
        }

    # No native output is read or interpreted until every input above passes.
    date_keys = {"Start": "start", "Finish": "finish",
                 "EarlyStart": "early_start", "EarlyFinish": "early_finish"}
    for case, spec in generate.TASKS.items():
        name = f"RC01-CASE-{case}"
        row = task_rows[name]
        tasks[case].update({
            "duration": _text(row, "Duration"),
            "remaining_duration": _text(row, "RemainingDuration"),
            **{date_keys[field]: _datetime(_text(row, field), f"{name}.{field}").isoformat()
               for field in DATE_FIELDS},
        })
        for duration_field in ("Duration", "RemainingDuration"):
            _require(re.fullmatch(r"PT[0-9]+H[0-9]+M[0-9]+S",
                                  _text(row, duration_field) or "") is not None,
                     f"native duration invalid: {name}.{duration_field}")
        for manual_field, derived_field in (("ManualStart", "Start"),
                                            ("ManualFinish", "Finish"),
                                            ("ManualDuration", "Duration")):
            _require(_text(row, manual_field) in (None, _text(row, derived_field)),
                     f"unexplained manual save field: {name}.{manual_field}")
    for row in assignment_rows:
        uid = int(_text(row, "UID") or "0")
        assignments[uid].update({
            "start": _datetime(_text(row, "Start"), f"assignment {uid}.Start").isoformat(),
            "finish": _datetime(_text(row, "Finish"), f"assignment {uid}.Finish").isoformat(),
        })
        timephased = row.findall("p:TimephasedData", NS)
        _require(len(timephased) <= 1, f"assignment timephased allocation changed: {uid}")
        if timephased:
            entry = timephased[0]
            for field, value in {
                "Type": "1", "UID": str(uid), "Unit": "1",
                "Value": generate.ASSIGNMENT_WORK,
                "Start": _text(row, "Start"), "Finish": _text(row, "Finish"),
            }.items():
                _require(_text(entry, field) == value,
                         f"assignment timephased allocation changed: {uid}.{field}")
            _require(len(entry) == 6, f"assignment timephased fields changed: {uid}")

    return {
        "project": {
            "name": _text(root, "Name"),
            "guid": _text(root, "GUID"),
            "build_number": _text(root, "BuildNumber"),
            "start": _text(root, "StartDate"),
            "calendar_uid": _text(root, "CalendarUID"),
        },
        "calendars": {
            uid: {
                "name": spec["name"],
                "intervals": [list(row) for row in spec["intervals"]],
            }
            for uid, spec in generate.CALENDARS.items()
        },
        "resources": resources,
        "tasks": tasks,
        "assignments": assignments,
        "assignment_order": [int(value) for value in order if value is not None],
    }


def _dt(value: object) -> datetime:
    if not isinstance(value, str):
        raise NativeEvidenceError("classification observation is missing a date")
    return _datetime(value, "classification observation")


def _case_observations(parsed: dict[str, object]) -> dict[str, object]:
    tasks = parsed["tasks"]
    assignments = parsed["assignments"]
    observations: dict[str, object] = {}
    for case in "ABCD":
        case_assignments = [
            row for row in assignments.values() if row["case"] == case
        ]
        task = tasks[case]
        observations[case] = {
            "task": {
                "start": task["start"],
                "finish": task["finish"],
                "early_start": task["early_start"],
                "early_finish": task["early_finish"],
                "duration": task["duration"],
                "remaining_duration": task["remaining_duration"],
            },
            "assignments": {
                str(row["uid"]): {
                    "uid": row["uid"],
                    "role": row["role"],
                    "resource_uid": row["resource_uid"],
                    "start": row["start"],
                    "finish": row["finish"],
                    "work": row["work"],
                    "units": row["units"],
                }
                for row in case_assignments
            },
            "union_prediction": {
                "start": generate.PROJECT_START,
                "finish": "2026-10-12T12:00:00",
            },
        }
    return observations


def classify(observations: dict[str, object]) -> dict[str, object]:
    def task(case: str, field: str) -> datetime:
        return _dt(observations[case]["task"][field])

    def assignment(case: str, role: str, field: str) -> datetime:
        matches = [
            row
            for row in observations[case]["assignments"].values()
            if row["role"] == role
        ]
        _require(len(matches) == 1, f"case {case} does not have one {role} assignment")
        return _dt(matches[0][field])

    assignment_calendar_compatible: dict[str, bool] = {}
    for case in "ABCD":
        for uid, row in observations[case]["assignments"].items():
            role = row["role"]
            expected = (
                (datetime(2026, 10, 12, 13), datetime(2026, 10, 12, 17))
                if role == "PM"
                else (datetime(2026, 10, 12, 8), datetime(2026, 10, 12, 12))
            )
            assignment_calendar_compatible[f"{case}.{uid}"] = (
                _dt(row["start"]) == expected[0]
                and _dt(row["finish"]) == expected[1]
                and row["work"] == generate.ASSIGNMENT_WORK
                and Decimal(str(row["units"])) == Decimal(generate.ASSIGNMENT_UNITS)
            )

    envelope_checks: dict[str, bool] = {}
    for case in "ABC":
        spans = observations[case]["assignments"].values()
        envelope_checks[case] = (
            task(case, "start") == min(_dt(row["start"]) for row in spans)
            and task(case, "finish") == max(_dt(row["finish"]) for row in spans)
            and task(case, "early_start") == task(case, "start")
            and task(case, "early_finish") == task(case, "finish")
        )

    order_twin = (
        all(task("A", field) == task("B", field)
            for field in ("start", "finish", "early_start", "early_finish"))
        and all(observations["A"]["task"][field]
                == observations["B"]["task"][field]
                for field in ("duration", "remaining_duration"))
        and all(
            assignment("A", role, field) == assignment("B", role, field)
            for role in ("AM", "PM")
            for field in ("start", "finish")
        )
    )
    overlap_control = (
        envelope_checks["C"]
        and task("C", "start") == datetime(2026, 10, 12, 8)
        and task("C", "finish") == datetime(2026, 10, 12, 12)
    )
    single_rows = list(observations["D"]["assignments"].values())
    _require(len(single_rows) == 1, "case D does not have exactly one assignment")
    single = single_rows[0]
    single_control = (
        task("D", "start") == _dt(single["start"])
        and task("D", "finish") == _dt(single["finish"])
        and task("D", "early_start") == task("D", "start")
        and task("D", "early_finish") == task("D", "finish")
        and task("D", "start") == datetime(2026, 10, 12, 8)
        and task("D", "finish") == datetime(2026, 10, 12, 12)
    )
    separated_differs_from_union = all(
        task(case, "finish")
        != _dt(observations[case]["union_prediction"]["finish"])
        for case in "AB"
    )
    duration_matches_assignment_work = all(
        observations[case]["task"]["duration"]
        == ("PT8H0M0S" if case in "AB" else "PT4H0M0S")
        and observations[case]["task"]["remaining_duration"]
        == observations[case]["task"]["duration"]
        for case in "ABCD"
    )
    coherent_union_rejection = all(
        task(case, "start") == datetime(2026, 10, 12, 8)
        and task(case, "finish") == datetime(2026, 10, 12, 12)
        and task(case, "early_start") == task(case, "start")
        and task(case, "early_finish") == task(case, "finish")
        and observations[case]["task"]["duration"] == "PT4H0M0S"
        and observations[case]["task"]["remaining_duration"] == "PT4H0M0S"
        for case in "AB"
    )
    controls_valid = (
        overlap_control
        and single_control
        and all(assignment_calendar_compatible.values())
    )
    predicates = {
        "all_assignment_spans_match_their_resource_calendars": all(
            assignment_calendar_compatible.values()
        ),
        "two_assignment_tasks_equal_assignment_envelopes": all(
            envelope_checks.values()
        ),
        "assignment_order_twin_is_identical": order_twin,
        "overlap_control_is_valid": overlap_control,
        "single_resource_control_is_valid": single_control,
        "separated_cases_differ_from_union_prediction": separated_differs_from_union,
        "duration_is_consistent_with_assignment_work": duration_matches_assignment_work,
    }
    if all(predicates.values()):
        verdict = "V2_ASSIGNMENT_ENVELOPE_SUPPORTED"
    elif controls_valid and order_twin and coherent_union_rejection:
        verdict = "V2_ASSIGNMENT_ENVELOPE_REJECTED"
    else:
        verdict = "V2_NATIVE_RESULT_INCONCLUSIVE"
    return {
        "verdict": verdict,
        "predicates": predicates,
        "controls_valid": controls_valid,
        "assignment_calendar_compatibility": assignment_calendar_compatible,
        "envelope_checks": envelope_checks,
        "observations": observations,
    }


def analyze(payload: bytes) -> dict[str, object]:
    try:
        parsed = parse_and_validate(payload)
    except NativeEvidenceError as error:
        return {
            "schema": SCHEMA,
            "experiment_id": generate.EXPERIMENT_ID,
            "native_return": {"bytes": len(payload), "sha256": _sha256(payload)},
            "classification": {"verdict": "V2_INPUT_CONTRACT_VIOLATED",
                               "validation_failure": str(error)},
            "decision": {"native_experiment_passed": False,
                         "boiler_counterfactual_authorized": False,
                         "production_correction_authorized": False},
        }
    observations = _case_observations(parsed)
    generated = (
        len(payload) == generate.INPUT_BYTES
        and _sha256(payload) == generate.INPUT_SHA256
    )
    build = parsed["project"]["build_number"]
    if generated or not isinstance(build, str) or NATIVE_BUILD.fullmatch(build) is None:
        classification = {
            "verdict": "V2_NOT_RUN_UNRECALCULATED_INPUT",
            "predicates": {},
            "controls_valid": False,
            "observations": observations,
        }
    else:
        classification = classify(observations)
    passed = classification["verdict"] == "V2_ASSIGNMENT_ENVELOPE_SUPPORTED"
    return {
        "schema": SCHEMA,
        "experiment_id": generate.EXPERIMENT_ID,
        "input_identity": {
            "path": "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2.xml",
            "bytes": generate.INPUT_BYTES,
            "sha256": generate.INPUT_SHA256,
        },
        "native_return": {"bytes": len(payload), "sha256": _sha256(payload)},
        "project": parsed["project"],
        "predeclared_contract": {
            "fields_read": {
                "project_inputs": ["Name", "Title", "ScheduleFromStart", "StartDate", "CalendarUID", "DefaultStartTime", "DefaultFinishTime", "MinutesPerDay", "MinutesPerWeek", "DaysPerMonth", "DefaultTaskType", "NewTasksEffortDriven", "NewTasksAreManual", "HonorConstraints", "TaskUpdatesResource"],
                "project_native_identity_or_outputs": ["GUID", "BuildNumber", "FinishDate"],
                "task_inputs": [
                    "UID", "GUID", "ID", "Type", "EffortDriven",
                    "IgnoreResourceCalendar", "Work", "Start",
                    "CalendarUID", "ConstraintType", "Manual", "PercentComplete",
                    "LevelAssignments", "LevelingCanSplit", "LevelingDelay",
                ],
                "task_outputs": ["Duration", "RemainingDuration", "Finish", "EarlyStart", "EarlyFinish", "LateStart", "LateFinish", "FreeSlack", "TotalSlack", "Critical"],
                "resource_inputs": ["UID", "ID", "CalendarUID", "MaxUnits", "CanLevel"],
                "resource_native_identity_or_outputs": ["GUID", "PeakUnits", "OverAllocated"],
                "assignment_inputs": [
                    "UID", "GUID", "TaskUID", "ResourceUID", "Work", "Units",
                    "ActualWork", "RemainingWork", "Delay", "LevelingDelay",
                ],
                "assignment_outputs": ["Start", "Finish"],
                "calendar_inputs": ["UID", "GUID", "BaseCalendarUID", "WeekDays.WorkingTimes"],
                "calendar_save_normalization": ["UID 2-5 display Name may become Unassigned; omission of inherited non-working weekend days only"],
            },
            "controls": {
                "C": "two distinct but fully overlapping resource calendars",
                "D": "single-resource supported-rule control",
            },
            "acceptance": "all seven predicates in classification.predicates are true; A/B 8h, C/D 4h; union prediction 08:00-12:00 for four declared working hours",
            "support": "V2_ASSIGNMENT_ENVELOPE_SUPPORTED",
            "rejection": (
                "valid controls and order twin; both A/B follow exact 08:00-12:00 "
                "four-hour union placement despite valid PM assignments to 17:00"
            ),
            "inconclusive": "any invalid control, order effect, unknown normalization or mixed observation",
            "stopping_rule": (
                "support authorizes only a later diagnostic BOILER counterfactual; "
                "rejection or inconclusive stops RC01 without a production change"
            ),
        },
        "classification": classification,
        "decision": {
            "native_experiment_passed": passed,
            "boiler_counterfactual_authorized": passed,
            "production_correction_authorized": False,
        },
    }


def serialize(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def refuse_output_alias(output: Path, sources: Mapping[str, Path]) -> None:
    output_resolved = output.resolve(strict=False)
    for role, source in sources.items():
        same_path = output_resolved == source.resolve(strict=False)
        same_object = False
        if output.exists() or output.is_symlink():
            try:
                same_object = output.samefile(source)
            except FileNotFoundError:
                same_object = False
            except OSError as error:
                raise NativeEvidenceError(
                    f"cannot establish whether output is separate from {role}"
                ) from error
        if same_path or same_object:
            raise NativeEvidenceError(f"output must be separate from {role}")


def write_output_safely(
    output: Path,
    payload: str,
    sources: Mapping[str, Path],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    refuse_output_alias(output, sources)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        refuse_output_alias(output, sources)
        os.replace(temporary, output)
        temporary = None
        directory_descriptor = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as error:
        raise NativeEvidenceError(f"cannot safely publish native evidence: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("native_return", type=Path)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--check", type=Path)
    args = parser.parse_args()
    sources = {
        "native return": args.native_return,
        "pinned V2 input": ROOT / "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2.xml",
        "historical V1 input": ROOT / "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1.xml",
        "V1 invalid-return receipt": ROOT / "docs/evidence/p1-g2-rc01-native-v1-invalid-return-2026-09-28.json",
    }
    if args.output:
        refuse_output_alias(args.output, sources)
    if args.check:
        refuse_output_alias(args.check, sources)
    before = args.native_return.read_bytes()
    payload = serialize(analyze(before))
    if args.native_return.read_bytes() != before:
        raise NativeEvidenceError("native return changed while it was being analyzed")
    if args.check:
        if args.check.read_bytes() != payload.encode("utf-8"):
            raise SystemExit("candidate evidence does not match this native return")
    elif args.output:
        write_output_safely(args.output, payload, sources)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
