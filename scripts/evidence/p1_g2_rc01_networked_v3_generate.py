#!/usr/bin/env python3
"""Fixed synthetic, networked RC01 MSPDI. Never contains customer identities."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence import p1_g2_rc01_assignment_native_generate as base

URI = base.URI
q = base.q
add = base.add
EXPERIMENT_ID = "P1-G2-RC01-NETWORKED-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V3"
PREREGISTRATION_ID = EXPERIMENT_ID + "-R3-WORKING-DURATION"
PROJECT_NAME = EXPERIMENT_ID + ".xml"
# The valid V2 save kept Project.Name only when its basename was unchanged.
# Save V3 into a *different directory* using this same basename.
RETURN_NAME = PROJECT_NAME
PROJECT_START = "2026-10-12T08:00:00"
FIXTURE = Path("tests/fixtures") / PROJECT_NAME
AUDIT = Path("docs/evidence/p1-g2-rc01-boiler-counterfactual-reviewed-v3-2026-09-28.json")
AUDIT_SHA256 = "4a7b32e7050b8eb61860d08cc26e544e01e924f4096576ea67009c04c318b248"
INPUT_BYTES = 122_492
INPUT_SHA256 = "c9c1ef3b6c850bfed1a0ecd41e6ad0fb69e4aac367ef578548c90986529df4e9"
ZERO = "PT0H0M0S"
NAMESPACE = uuid.UUID("a76d7892-c4cc-4b09-bba5-f093747dad63")


def guid(kind: str, identity: int | str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"v3/{kind}/{identity}"))


CALENDARS = {
    1: ("V3-PROJECT-8H", "PROJECT-8H"),
    2: ("V3-RESOURCE-24H", "24H"),
    3: ("V3-RESOURCE-10H", "10H"),
    4: ("V3-RESOURCE-10H-IDENTITY-TWIN", "10H"),
}
INTERVALS = {"24H": (("00:00:00", "00:00:00"),),
             "10H": (("07:00:00", "17:00:00"),),
             "PROJECT-8H": (("07:30:00", "15:30:00"),)}
# Each shape is (declared task duration hours, productive assignment hours).
SHAPES = {"A": (4, 2), "B": (4, 4), "C": (8, 4),
          "D": (8, 4), "E": (4, 3), "F": (12, 6)}
CASES = ("A", "A-ORDER-TWIN", "B", "C", "C-CALENDAR-IDENTITY-TWIN",
         "D", "E", "F", "ADJACENT-RC01", "GAP")


def graph() -> tuple[dict[str, dict], list[dict], dict[int, dict]]:
    """Pure frozen topology; an independent long path sets project finish."""
    tasks: dict[str, dict] = {}
    edges: list[dict] = []
    assignments: dict[int, dict] = {}

    def task(name: str, duration: int, predecessors: tuple[str, ...] = (),
             kind: str = "control", calendar: int = 2) -> None:
        uid = len(tasks) + 1
        tasks[name] = dict(uid=uid, name=name, duration=duration, kind=kind,
                           predecessors=predecessors)
        for predecessor in predecessors:
            edges.append(dict(predecessor=predecessor, successor=name, type=1, lag=0))
        if kind == "control":
            assignments[1000 + uid] = dict(uid=1000 + uid, task=name,
                                            calendar=calendar, work=duration,
                                            units=1, role="control")

    def candidate(name: str, shape: str, predecessors: tuple[str, ...],
                  second_calendar: int = 3, reverse: bool = False) -> None:
        task(name, SHAPES[shape][0], predecessors, shape)
        uid = tasks[name]["uid"]
        duration = SHAPES[shape][1]
        rows = [("24H", 2, 2 * duration, 2),
                ("10H", second_calendar, duration, 1)]
        if reverse:
            rows.reverse()
        for ordinal, (role, calendar, work, units) in enumerate(rows, 1):
            assignment_uid = uid * 10 + ordinal
            assignments[assignment_uid] = dict(uid=assignment_uid, task=name,
                                               calendar=calendar, work=work,
                                               units=units, role=role)

    for case in CASES:
        if case == "ADJACENT-RC01":
            task("ADJACENT-PRE", 1)
            candidate("ADJACENT-C", "C", ("ADJACENT-PRE",))
            candidate("ADJACENT-B", "B", ("ADJACENT-C",))
            task("ADJACENT-POST", 2, ("ADJACENT-B",))
            continue
        task(f"{case}-PRE", 8 if case == "GAP" else 1)
        candidate(case, "A" if case == "GAP" else case[0], (f"{case}-PRE",),
                  second_calendar=4 if case == "C-CALENDAR-IDENTITY-TWIN" else 3,
                  reverse=case == "A-ORDER-TWIN")
        if case == "D":
            # Independent holds yield positive D free float; unequal branch
            # durations make the seven-hour branch the unique late driver.
            task("D-HOLD-SHORT", 32)
            task("D-HOLD-LONG", 36)
            task("D-POST", 1, (case, "D-HOLD-SHORT"))
            task("D-POST-LONG", 7, (case, "D-HOLD-LONG"))
        else:
            task(f"{case}-POST", 2, (case,))
    task("FINISH-DRIVER", 72)
    return tasks, edges, assignments


def _week(row: ET.Element, intervals: tuple[tuple[str, str], ...], *, all_days: bool) -> None:
    week = ET.SubElement(row, q("WeekDays"))
    for day in range(1, 8):
        element = ET.SubElement(week, q("WeekDay"))
        add(element, "DayType", day)
        working_day = all_days or 2 <= day <= 6
        add(element, "DayWorking", 1 if working_day else 0)
        if not working_day:
            continue
        working = ET.SubElement(element, q("WorkingTimes"))
        for start, end in intervals:
            interval = ET.SubElement(working, q("WorkingTime"))
            add(interval, "FromTime", start)
            add(interval, "ToTime", end)


def duration(hours: int) -> str:
    return f"PT{hours}H0M0S"


def build_fixture() -> bytes:
    tasks, edges, assignments = graph()
    root = ET.Element(q("Project"))
    for key, value in (("SaveVersion", 14), ("BuildNumber", "0.0.0.0"),
                       ("Name", PROJECT_NAME), ("GUID", guid("project", 1)),
                       ("Title", EXPERIMENT_ID), ("ScheduleFromStart", 1),
                       ("StartDate", PROJECT_START), ("FinishDate", "2026-10-19T08:00:00"),
                       ("CalendarUID", 1), ("DefaultStartTime", "07:30:00"),
                       ("DefaultFinishTime", "15:30:00"), ("MinutesPerDay", 480),
                       ("MinutesPerWeek", 2400), ("DaysPerMonth", 20),
                       ("DefaultTaskType", 0), ("NewTasksEffortDriven", 0),
                       ("NewTasksEstimated", 0), ("AutoLink", 0),
                       ("NewTasksAreManual", 0), ("ProjectExternallyEdited", 0),
                       ("MultipleCriticalPaths", 0), ("CriticalSlackLimit", 0)):
        add(root, key, value)
    calendars = ET.SubElement(root, q("Calendars"))
    for uid, (name, semantic) in CALENDARS.items():
        row = ET.SubElement(calendars, q("Calendar"))
        for key, value in (("UID", uid), ("GUID", guid("calendar", uid)),
                           ("Name", name), ("IsBaseCalendar", 1 if uid == 1 else 0),
                           ("IsBaselineCalendar", 0),
                           ("BaseCalendarUID", -1 if uid == 1 else 1)):
            add(row, key, value)
        _week(row, INTERVALS[semantic], all_days=uid != 1)
    task_container = ET.SubElement(root, q("Tasks"))
    for name, spec in tasks.items():
        row = ET.SubElement(task_container, q("Task"))
        work = sum(a["work"] for a in assignments.values() if a["task"] == name)
        for key, value in (("UID", spec["uid"]), ("GUID", guid("task", name)),
                           ("ID", spec["uid"]), ("Name", f"V3-{name}"),
                           ("Active", 1), ("Manual", 0), ("Type", 0), ("IsNull", 0),
                           ("CreateDate", "2026-09-28T08:00:00"), ("WBS", spec["uid"]),
                           ("OutlineNumber", spec["uid"]), ("OutlineLevel", 1),
                           ("Priority", 500), ("Start", PROJECT_START),
                           ("Finish", "2026-10-12T12:00:00"),
                           ("Duration", duration(spec["duration"])), ("DurationFormat", 7),
                           ("Work", duration(work)), ("EffortDriven", 0),
                           ("Recurring", 0), ("OverAllocated", 0), ("Estimated", 0),
                           ("Milestone", 0), ("Summary", 0), ("Critical", 0),
                           ("EarlyStart", PROJECT_START),
                           ("EarlyFinish", "2026-10-12T12:00:00"),
                           ("LateStart", PROJECT_START),
                           ("LateFinish", "2026-10-12T12:00:00"),
                           ("FreeSlack", 12345), ("TotalSlack", 12345),
                           ("PercentComplete", 0), ("PercentWorkComplete", 0),
                           ("ActualDuration", ZERO), ("ActualWork", ZERO),
                           ("RegularWork", duration(work)),
                           ("RemainingDuration", duration(spec["duration"])),
                           ("RemainingWork", duration(work)), ("ConstraintType", 0),
                           ("LevelAssignments", 0), ("LevelingCanSplit", 0),
                           ("LevelingDelay", 0), ("LevelingDelayFormat", 7),
                           ("IgnoreResourceCalendar", 0), ("HideBar", 0),
                           ("Rollup", 0), ("PhysicalPercentComplete", 0),
                           ("IsPublished", 1)):
            add(row, key, value)
        for edge in edges:
            if edge["successor"] != name:
                continue
            link = ET.SubElement(row, q("PredecessorLink"))
            add(link, "PredecessorUID", tasks[edge["predecessor"]]["uid"])
            add(link, "Type", edge["type"])
            add(link, "LinkLag", edge["lag"])
            add(link, "LagFormat", 7)
    resources = ET.SubElement(root, q("Resources"))
    for assignment in assignments.values():
        uid = assignment["uid"]
        row = ET.SubElement(resources, q("Resource"))
        for key, value in (("UID", uid), ("GUID", guid("resource", uid)),
                           ("ID", uid), ("Name", f"V3-RESOURCE-{uid}"), ("Type", 1),
                           ("IsNull", 0), ("Initials", f"R{uid}"),
                           ("MaxUnits", assignment["units"]), ("PeakUnits", assignment["units"]),
                           ("OverAllocated", 0), ("CanLevel", 0),
                           ("Work", ZERO), ("RegularWork", ZERO), ("ActualWork", ZERO),
                           ("RemainingWork", ZERO), ("PercentWorkComplete", 0),
                           ("CalendarUID", assignment["calendar"]),
                           ("IsGeneric", 0), ("IsInactive", 0), ("IsEnterprise", 0),
                           ("IsCostResource", 0), ("IsBudget", 0)):
            add(row, key, value)
    assignment_container = ET.SubElement(root, q("Assignments"))
    for spec in assignments.values():
        uid = spec["uid"]
        row = ET.SubElement(assignment_container, q("Assignment"))
        for key, value in (("UID", uid), ("GUID", guid("assignment", uid)),
                           ("TaskUID", tasks[spec["task"]]["uid"]), ("ResourceUID", uid),
                           ("PercentWorkComplete", 0), ("ActualWork", ZERO),
                           ("RemainingWork", duration(spec["work"])),
                           ("Work", duration(spec["work"])), ("Start", PROJECT_START),
                           ("Finish", "2026-10-12T12:00:00"), ("Units", spec["units"]),
                           ("Delay", 0), ("LevelingDelay", 0),
                           ("LevelingDelayFormat", 7), ("Milestone", 0),
                           ("Overallocated", 0), ("WorkContour", 0), ("Confirmed", 1),
                           ("ResponsePending", 0), ("UpdateNeeded", 0),
                           ("CreationDate", "2026-09-28T08:00:00")):
            add(row, key, value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def root_mapping(path: Path) -> dict[str, dict]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != AUDIT_SHA256:
        raise ValueError("merged BOILER applicability audit identity changed")
    rows = json.loads(raw)["applicability"]
    result = {}
    for row in rows:
        semantic_by_source_uid = {"13": "24H", "14": "10H", "45": "10H"}
        if (len(row["assignments"]) != 2 or row["distinct_resource_calendar_count"] != 2
                or row["resource_count"] != 2 or
                any(a["calendar_uid"] not in semantic_by_source_uid or
                    a["work_seconds"] % 3600 or a["units_permille"] % 1000
                    for a in row["assignments"])):
            raise ValueError(f"unknown allocation/calendar shape: {row['leaf_id']}")
        actual = sorted((a["work_seconds"] // 3600, a["units_permille"] // 1000,
                         semantic_by_source_uid[a["calendar_uid"]])
                        for a in row["assignments"])
        matching = [name for name, (hours, effective) in SHAPES.items() if name != "D"
                    if hours * 3600 == row["planned_duration_seconds"]
                    and actual == sorted(((2 * effective, 2, "24H"),
                                          (effective, 1, "10H")))]
        if len(matching) != 1 or row["task_type"] != "fixed_units" or row["manual"] or not row["active"] or row["effort_driven"] or row["ignore_resource_calendar"] or row["constraint"] is not None or row["task_calendar_uid"] is not None or row["progress_state"] != "not_started" or row["remaining_duration_seconds"] != row["planned_duration_seconds"] or len(row["predecessors"]) != 1 or any(edge["type"] != "FS" or edge["lag_seconds"] for edge in row["predecessors"] + row["successors"]) or len(row["successors"]) not in (1, 2) or any(a["delay_tenths_minutes"] or a["leveling_delay_tenths_minutes"] for a in row["assignments"]):
            raise ValueError(f"unmapped current BOILER root shape: {row['leaf_id']}")
        shape = matching[0]
        if len(row["successors"]) == 2:
            if shape != "C":
                raise ValueError("fan-out shape differs")
            shape = "D"
        if row["leaf_id"] == "L0084":
            if shape != "C" or not any(e["leaf_id"] == "L0080" for e in row["successors"]):
                raise ValueError("adjacent RC01 topology differs")
        if row["leaf_id"] == "L0080" and not any(e["leaf_id"] == "L0084" for e in row["predecessors"]):
            raise ValueError("adjacent RC01 predecessor differs")
        if any(a["calendar_uid"] == "45" for a in row["assignments"]):
            if shape != "C":
                raise ValueError("calendar identity twin differs")
            native = "C-CALENDAR-IDENTITY-TWIN"
        else:
            native = shape
        result[row["leaf_id"]] = {"class": shape, "native_case": native,
                                   "adjacent_case": "ADJACENT-RC01" if row["leaf_id"] in ("L0084", "L0080") else None,
                                   "duration_hours": row["planned_duration_seconds"] // 3600,
                                   "allocation": actual, "predecessors": len(row["predecessors"]),
                                   "successors": len(row["successors"])}
    if len(result) != 10:
        raise ValueError("ten current root shapes required")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = build_fixture()
    if len(payload) != INPUT_BYTES or hashlib.sha256(payload).hexdigest() != INPUT_SHA256:
        raise ValueError("V3 generator diverged from fixed fixture")
    args.output.write_bytes(payload)
    print(json.dumps({"path": str(args.output), "bytes": len(payload),
                      "sha256": hashlib.sha256(payload).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
