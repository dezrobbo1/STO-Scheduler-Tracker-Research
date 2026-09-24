#!/usr/bin/env python3
"""Generate the synthetic P1-G2 RC02 inactive fan-out MSPDI matrix."""
from __future__ import annotations

from datetime import datetime, timedelta
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

URI = "http://schemas.microsoft.com/project"
ET.register_namespace("", URI)

PROJECT_NAME = "P1-G2-RC02-Inactive-Fanout-Native-Matrix.xml"
SENTINEL_FREE_SLACK = "12345"


def q(tag: str) -> str:
    return f"{{{URI}}}{tag}"


def add(parent: ET.Element, tag: str, value: object) -> ET.Element:
    child = ET.SubElement(parent, q(tag))
    child.text = str(value)
    return child


def build_fixture() -> bytes:
    start = datetime(2026, 10, 12, 8, 0, 0)
    root = ET.Element(q("Project"))
    for tag, value in (
        ("SaveVersion", "14"), ("BuildNumber", "16.0"),
        ("Name", PROJECT_NAME),
        ("GUID", "33333333-3333-4333-8333-333333333333"),
        ("Title", "P1-G2 RC02 inactive fan-out native matrix"),
        ("ScheduleFromStart", "1"), ("StartDate", start.isoformat()),
        ("FinishDate", (start + timedelta(days=14)).isoformat()),
        ("CalendarUID", "1"), ("DefaultStartTime", "08:00:00"),
        ("DefaultFinishTime", "17:00:00"), ("MinutesPerDay", "1440"),
        ("MinutesPerWeek", "10080"), ("DaysPerMonth", "30"),
        ("DefaultTaskType", "1"), ("NewTasksEffortDriven", "0"),
        ("NewTasksEstimated", "0"), ("SplitsInProgressTasks", "1"),
        ("WeekStartDay", "1"), ("Autolink", "0"), ("NewTaskStartDate", "0"),
        ("NewTasksAreManual", "0"), ("ProjectExternallyEdited", "0"),
    ):
        add(root, tag, value)

    calendars = ET.SubElement(root, q("Calendars"))
    calendar = ET.SubElement(calendars, q("Calendar"))
    for tag, value in (
        ("UID", "1"), ("GUID", "44444444-4444-4444-8444-444444444444"),
        ("Name", "24 Hours"), ("IsBaseCalendar", "1"),
        ("IsBaselineCalendar", "0"), ("BaseCalendarUID", "-1"),
    ):
        add(calendar, tag, value)
    weekdays = ET.SubElement(calendar, q("WeekDays"))
    for day in range(1, 8):
        weekday = ET.SubElement(weekdays, q("WeekDay"))
        add(weekday, "DayType", day)
        add(weekday, "DayWorking", "1")
        times = ET.SubElement(weekday, q("WorkingTimes"))
        working = ET.SubElement(times, q("WorkingTime"))
        add(working, "FromTime", "00:00:00")
        add(working, "ToTime", "00:00:00")

    tasks = ET.SubElement(root, q("Tasks"))

    def task(
        uid: int,
        name: str,
        hours: int,
        predecessors: tuple[int, ...] = (),
        *,
        active: bool = True,
        free_slack: str = "0",
    ) -> None:
        row = ET.SubElement(tasks, q("Task"))
        finish = start + timedelta(hours=hours)
        for tag, value in (
            ("UID", uid), ("GUID", f"55555555-5555-4555-8555-{uid:012d}"),
            ("ID", uid), ("Name", name), ("Active", "1" if active else "0"),
            ("Manual", "0"), ("Type", "1"), ("IsNull", "0"),
            ("CreateDate", "2026-09-25T08:00:00"), ("WBS", uid),
            ("OutlineNumber", uid), ("OutlineLevel", "1"), ("Priority", "500"),
            ("Start", start.isoformat()), ("Finish", finish.isoformat()),
            ("Duration", f"PT{hours}H0M0S"), ("ManualStart", start.isoformat()),
            ("ManualFinish", finish.isoformat()), ("ManualDuration", f"PT{hours}H0M0S"),
            ("DurationFormat", "7"), ("Work", "PT0H0M0S"), ("ResumeValid", "0"),
            ("EffortDriven", "0"), ("Recurring", "0"), ("OverAllocated", "0"),
            ("Estimated", "0"), ("Milestone", "0"), ("Summary", "0"),
            ("Critical", "0"), ("IsSubproject", "0"), ("IsSubprojectReadOnly", "0"),
            ("ExternalTask", "0"), ("EarlyStart", start.isoformat()),
            ("EarlyFinish", finish.isoformat()), ("LateStart", start.isoformat()),
            ("LateFinish", finish.isoformat()), ("FreeSlack", free_slack),
            ("TotalSlack", "0"), ("PercentComplete", "0"),
            ("PercentWorkComplete", "0"), ("ActualDuration", "PT0H0M0S"),
            ("ActualWork", "PT0H0M0S"), ("RegularWork", "PT0H0M0S"),
            ("RemainingDuration", f"PT{hours}H0M0S"), ("RemainingWork", "PT0H0M0S"),
            ("ConstraintType", "0"), ("CalendarUID", "1"), ("LevelAssignments", "1"),
            ("LevelingCanSplit", "1"), ("LevelingDelay", "0"),
            ("LevelingDelayFormat", "7"), ("IgnoreResourceCalendar", "1"),
            ("HideBar", "0"), ("Rollup", "0"), ("PhysicalPercentComplete", "0"),
            ("EarnedValueMethod", "0"), ("IsPublished", "1"), ("CommitmentType", "0"),
        ):
            add(row, tag, value)
        for predecessor in predecessors:
            link = ET.SubElement(row, q("PredecessorLink"))
            add(link, "PredecessorUID", predecessor)
            add(link, "Type", "1")
            add(link, "CrossProject", "0")
            add(link, "LinkLag", "0")
            add(link, "LagFormat", "7")

    # Independent project-finish driver: fourteen 24-hour days.
    task(1, "RC02-FANOUT-FINISH-DRIVER", 336)

    # Pair A: both successors are visibly driven by MID while active. S1 is the
    # earlier late boundary because it has the longer duration.
    task(2, "RC02-FO-A-A-PRED", 24)
    task(3, "RC02-FO-A-A-MID", 48, (2,))
    task(4, "RC02-FO-A-A-S1", 96, (3,))
    task(5, "RC02-FO-A-A-S2", 24, (3,))
    task(6, "RC02-FO-A-I-PRED", 24)
    task(7, "RC02-FO-A-I-MID", 48, (6,), active=False)
    task(8, "RC02-FO-A-I-S1", 96, (7,))
    task(9, "RC02-FO-A-I-S2", 24, (7,))

    # Pair B mirrors the BOILER fan-out shape: S1 has only the inactive incoming
    # path; S2 also has an ordinary active predecessor that drives it forward.
    # S2 is the earlier late boundary, reversing the late-bound winner from A.
    task(10, "RC02-FO-B-A-PRED", 24)
    task(11, "RC02-FO-B-A-MID", 48, (10,))
    task(12, "RC02-FO-B-A-OTHER", 96)
    task(13, "RC02-FO-B-A-S1", 24, (11,))
    task(14, "RC02-FO-B-A-S2", 96, (11, 12))
    task(15, "RC02-FO-B-I-PRED", 24)
    task(16, "RC02-FO-B-I-MID", 48, (15,), active=False)
    task(17, "RC02-FO-B-I-OTHER", 96)
    task(18, "RC02-FO-B-I-S1", 24, (16,))
    task(19, "RC02-FO-B-I-S2", 96, (16, 17))

    # Pair C is the Free-Slack discriminator. Both active successors are driven
    # later by ordinary predecessors, so the direct active-successor gap is
    # positive while the original edge to inactive MID has a zero gap. The
    # deliberately non-zero sentinel prevents unchanged-value retention from
    # masquerading as a recalculated observation.
    task(20, "RC02-FO-C-A-PRED", 24)
    task(21, "RC02-FO-C-A-MID", 48, (20,))
    task(22, "RC02-FO-C-A-O1", 96)
    task(23, "RC02-FO-C-A-O2", 120)
    task(24, "RC02-FO-C-A-S1", 24, (21, 22))
    task(25, "RC02-FO-C-A-S2", 48, (21, 23))
    task(26, "RC02-FO-C-I-PRED", 24, free_slack=SENTINEL_FREE_SLACK)
    task(27, "RC02-FO-C-I-MID", 48, (26,), active=False)
    task(28, "RC02-FO-C-I-O1", 96)
    task(29, "RC02-FO-C-I-O2", 120)
    task(30, "RC02-FO-C-I-S1", 24, (27, 28))
    task(31, "RC02-FO-C-I-S2", 48, (27, 29))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
