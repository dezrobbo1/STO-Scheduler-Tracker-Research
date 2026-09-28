#!/usr/bin/env python3
"""Generate the exact synthetic RC01 assignment-envelope MSPDI matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

URI = "http://schemas.microsoft.com/project"
ET.register_namespace("", URI)

EXPERIMENT_ID = "P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1"
PROJECT_NAME = f"{EXPERIMENT_ID}.xml"
PROJECT_START = "2026-10-12T08:00:00"
PROJECT_GUID = "01010101-0101-4101-8101-010101010101"
TASK_DURATION = "PT4H0M0S"
ASSIGNMENT_WORK = "PT4H0M0S"
ASSIGNMENT_UNITS = "1"
INPUT_BYTES = 20_989
INPUT_SHA256 = "9d7ad7a8a845fcf036827fe90b51d41431d0452ece57097ce86934bec8119313"

CALENDARS = {
    1: {
        "name": "RC01-PROJECT-CALENDAR",
        "guid": "02010101-0101-4201-8201-010101010101",
        "intervals": (("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")),
        "base": -1,
    },
    2: {
        "name": "RC01-AM-CALENDAR",
        "guid": "02020202-0202-4202-8202-020202020202",
        "intervals": (("08:00:00", "12:00:00"),),
        "base": 1,
    },
    3: {
        "name": "RC01-PM-CALENDAR",
        "guid": "02030303-0303-4303-8303-030303030303",
        "intervals": (("13:00:00", "17:00:00"),),
        "base": 1,
    },
    4: {
        "name": "RC01-OVERLAP-1-CALENDAR",
        "guid": "02040404-0404-4404-8404-040404040404",
        "intervals": (("08:00:00", "12:00:00"),),
        "base": 1,
    },
    5: {
        "name": "RC01-OVERLAP-2-CALENDAR",
        "guid": "02050505-0505-4505-8505-050505050505",
        "intervals": (("08:00:00", "12:00:00"),),
        "base": 1,
    },
}

TASKS = {
    "A": {"uid": 1, "guid": "03010101-0101-4101-8101-010101010101", "work": "PT8H0M0S"},
    "B": {"uid": 2, "guid": "03020202-0202-4202-8202-020202020202", "work": "PT8H0M0S"},
    "C": {"uid": 3, "guid": "03030303-0303-4303-8303-030303030303", "work": "PT8H0M0S"},
    "D": {"uid": 4, "guid": "03040404-0404-4404-8404-040404040404", "work": "PT4H0M0S"},
}

RESOURCES = {
    1: {"name": "RC01-AM", "guid": "04010101-0101-4101-8101-010101010101", "calendar": 2},
    2: {"name": "RC01-PM", "guid": "04020202-0202-4202-8202-020202020202", "calendar": 3},
    3: {"name": "RC01-OVERLAP-1", "guid": "04030303-0303-4303-8303-030303030303", "calendar": 4},
    4: {"name": "RC01-OVERLAP-2", "guid": "04040404-0404-4404-8404-040404040404", "calendar": 5},
}

ASSIGNMENTS = (
    {"uid": 101, "guid": "05010101-0101-4101-8101-010101010101", "case": "A", "resource": 1, "role": "AM"},
    {"uid": 102, "guid": "05010202-0102-4102-8102-010201020102", "case": "A", "resource": 2, "role": "PM"},
    {"uid": 103, "guid": "05010303-0103-4103-8103-010301030103", "case": "B", "resource": 2, "role": "PM"},
    {"uid": 104, "guid": "05010404-0104-4104-8104-010401040104", "case": "B", "resource": 1, "role": "AM"},
    {"uid": 105, "guid": "05010505-0105-4105-8105-010501050105", "case": "C", "resource": 3, "role": "AM"},
    {"uid": 106, "guid": "05010606-0106-4106-8106-010601060106", "case": "C", "resource": 4, "role": "AM"},
    {"uid": 107, "guid": "05010707-0107-4107-8107-010701070107", "case": "D", "resource": 1, "role": "AM"},
)
ASSIGNMENT_ORDER = tuple(row["uid"] for row in ASSIGNMENTS)
ASSIGNMENT_ROLES = {row["uid"]: row["role"] for row in ASSIGNMENTS}


def q(tag: str) -> str:
    return f"{{{URI}}}{tag}"


def add(parent: ET.Element, tag: str, value: object) -> ET.Element:
    child = ET.SubElement(parent, q(tag))
    child.text = str(value)
    return child


def _week(calendar: ET.Element, intervals: tuple[tuple[str, str], ...]) -> None:
    weekdays = ET.SubElement(calendar, q("WeekDays"))
    for day in range(1, 8):
        weekday = ET.SubElement(weekdays, q("WeekDay"))
        add(weekday, "DayType", day)
        working = 2 <= day <= 6
        add(weekday, "DayWorking", "1" if working else "0")
        if not working:
            continue
        times = ET.SubElement(weekday, q("WorkingTimes"))
        for start, finish in intervals:
            row = ET.SubElement(times, q("WorkingTime"))
            add(row, "FromTime", start)
            add(row, "ToTime", finish)


def build_fixture() -> bytes:
    root = ET.Element(q("Project"))
    for tag, value in (
        ("SaveVersion", "14"),
        ("BuildNumber", "0.0.0.0"),
        ("Name", PROJECT_NAME),
        ("GUID", PROJECT_GUID),
        ("Title", EXPERIMENT_ID),
        ("ScheduleFromStart", "1"),
        ("StartDate", PROJECT_START),
        ("FinishDate", "2026-10-16T17:00:00"),
        ("CalendarUID", "1"),
        ("DefaultStartTime", "08:00:00"),
        ("DefaultFinishTime", "17:00:00"),
        ("MinutesPerDay", "480"),
        ("MinutesPerWeek", "2400"),
        ("DaysPerMonth", "20"),
        ("DefaultTaskType", "0"),
        ("NewTasksEffortDriven", "0"),
        ("NewTasksEstimated", "0"),
        ("AutoLink", "0"),
        ("NewTasksAreManual", "0"),
        ("ProjectExternallyEdited", "0"),
        ("MultipleCriticalPaths", "0"),
        ("CriticalSlackLimit", "0"),
    ):
        add(root, tag, value)

    calendars = ET.SubElement(root, q("Calendars"))
    for uid, spec in CALENDARS.items():
        row = ET.SubElement(calendars, q("Calendar"))
        for tag, value in (
            ("UID", uid),
            ("GUID", spec["guid"]),
            ("Name", spec["name"]),
            ("IsBaseCalendar", "1" if uid == 1 else "0"),
            ("IsBaselineCalendar", "0"),
            ("BaseCalendarUID", spec["base"]),
        ):
            add(row, tag, value)
        _week(row, spec["intervals"])

    tasks = ET.SubElement(root, q("Tasks"))
    for case, spec in TASKS.items():
        row = ET.SubElement(tasks, q("Task"))
        for tag, value in (
            ("UID", spec["uid"]),
            ("GUID", spec["guid"]),
            ("ID", spec["uid"]),
            ("Name", f"RC01-CASE-{case}"),
            ("Active", "1"),
            ("Manual", "0"),
            ("Type", "0"),
            ("IsNull", "0"),
            ("CreateDate", "2026-09-25T08:00:00"),
            ("WBS", spec["uid"]),
            ("OutlineNumber", spec["uid"]),
            ("OutlineLevel", "1"),
            ("Priority", "500"),
            ("Start", PROJECT_START),
            ("Finish", "2026-10-12T12:00:00"),
            ("Duration", TASK_DURATION),
            ("DurationFormat", "7"),
            ("Work", spec["work"]),
            ("EffortDriven", "0"),
            ("Recurring", "0"),
            ("OverAllocated", "0"),
            ("Estimated", "0"),
            ("Milestone", "0"),
            ("Summary", "0"),
            ("Critical", "0"),
            ("EarlyStart", PROJECT_START),
            ("EarlyFinish", "2026-10-12T12:00:00"),
            ("LateStart", PROJECT_START),
            ("LateFinish", "2026-10-12T12:00:00"),
            ("FreeSlack", "12345"),
            ("TotalSlack", "12345"),
            ("PercentComplete", "0"),
            ("PercentWorkComplete", "0"),
            ("ActualDuration", "PT0H0M0S"),
            ("ActualWork", "PT0H0M0S"),
            ("RegularWork", spec["work"]),
            ("RemainingDuration", TASK_DURATION),
            ("RemainingWork", spec["work"]),
            ("ConstraintType", "0"),
            ("LevelAssignments", "0"),
            ("LevelingCanSplit", "0"),
            ("LevelingDelay", "0"),
            ("LevelingDelayFormat", "7"),
            ("IgnoreResourceCalendar", "0"),
            ("HideBar", "0"),
            ("Rollup", "0"),
            ("PhysicalPercentComplete", "0"),
            ("IsPublished", "1"),
        ):
            add(row, tag, value)

    resources = ET.SubElement(root, q("Resources"))
    for uid, spec in RESOURCES.items():
        row = ET.SubElement(resources, q("Resource"))
        for tag, value in (
            ("UID", uid),
            ("GUID", spec["guid"]),
            ("ID", uid),
            ("Name", spec["name"]),
            ("Type", "1"),
            ("IsNull", "0"),
            ("Initials", spec["name"]),
            ("MaxUnits", "1"),
            ("PeakUnits", "1"),
            ("OverAllocated", "0"),
            ("CanLevel", "0"),
            ("Work", "PT0H0M0S"),
            ("RegularWork", "PT0H0M0S"),
            ("ActualWork", "PT0H0M0S"),
            ("RemainingWork", "PT0H0M0S"),
            ("PercentWorkComplete", "0"),
            ("CalendarUID", spec["calendar"]),
            ("IsGeneric", "0"),
            ("IsInactive", "0"),
            ("IsEnterprise", "0"),
            ("IsCostResource", "0"),
            ("IsBudget", "0"),
        ):
            add(row, tag, value)

    assignments = ET.SubElement(root, q("Assignments"))
    for spec in ASSIGNMENTS:
        row = ET.SubElement(assignments, q("Assignment"))
        for tag, value in (
            ("UID", spec["uid"]),
            ("GUID", spec["guid"]),
            ("TaskUID", TASKS[spec["case"]]["uid"]),
            ("ResourceUID", spec["resource"]),
            ("PercentWorkComplete", "0"),
            ("ActualWork", "PT0H0M0S"),
            ("RemainingWork", ASSIGNMENT_WORK),
            ("Work", ASSIGNMENT_WORK),
            ("Start", PROJECT_START),
            ("Finish", "2026-10-12T12:00:00"),
            ("Units", ASSIGNMENT_UNITS),
            ("Delay", "0"),
            ("LevelingDelay", "0"),
            ("LevelingDelayFormat", "7"),
            ("Milestone", "0"),
            ("Overallocated", "0"),
            ("WorkContour", "0"),
            ("Confirmed", "1"),
            ("ResponsePending", "0"),
            ("UpdateNeeded", "0"),
            ("CreationDate", "2026-09-25T08:00:00"),
        ):
            add(row, tag, value)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def canonical_import_contract(payload: bytes) -> dict[str, object]:
    """Describe which experiment fields survive today's canonical migration."""

    from sto.core.model.migrate.sto_v011 import migrate
    from sto.legacy import import_mspdi

    with tempfile.TemporaryDirectory(prefix="sto-rc01-matrix-") as directory:
        path = Path(directory) / PROJECT_NAME
        path.write_bytes(payload)
        schedule = migrate(import_mspdi(path))[0]
    calendar_uids = {row.uid for row in schedule.calendars}
    return {
        "activity_count": len(schedule.activities),
        "assignment_count": len(schedule.assignments),
        "assignment_start_finish_preserved": all(
            row.start is not None and row.finish is not None for row in schedule.assignments
        ),
        "resource_calendar_identity_preserved": all(
            row.calendar_uid in calendar_uids for row in schedule.resources
        ),
        "task_duration_type": schedule.activities[0].duration_type.value,
        "canonical_effort_driven": any(row.effort_driven for row in schedule.activities),
        "effort_driven_storage": "opaque_vendor_extension",
        "ignore_resource_calendar_storage": (
            "opaque_vendor_extension; clear value maps to canonical false semantic"
        ),
        "assignment_work_and_units_preserved": all(
            row.work.budgeted_seconds == 14_400
            and row.units.budgeted_permille == 1_000
            for row in schedule.assignments
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = build_fixture()
    args.output.write_bytes(payload)
    print(json.dumps({
        "path": str(args.output),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
