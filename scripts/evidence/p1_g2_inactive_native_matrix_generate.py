#!/usr/bin/env python3
"""Generate the all-synthetic P1-G2 RC02 inactive-activity MSPDI matrix."""
from __future__ import annotations

from datetime import datetime, timedelta
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

URI = "http://schemas.microsoft.com/project"
ET.register_namespace("", URI)

SENTINEL_FREE_SLACK = "12345"


def q(tag: str) -> str:
    return f"{{{URI}}}{tag}"


def add(parent: ET.Element, tag: str, value: object) -> ET.Element:
    child = ET.SubElement(parent, q(tag))
    child.text = str(value)
    return child


def build_fixture(*, pair_c_inactive_pred_free_slack: str = "0") -> bytes:
    start = datetime(2026, 10, 5, 8, 0, 0)
    root = ET.Element(q("Project"))
    for tag, value in (
        ("SaveVersion", "14"), ("BuildNumber", "16.0"),
        ("Name", "P1-G2-RC02-Inactive-Native-Matrix.xml"),
        ("GUID", "11111111-1111-4111-8111-111111111111"),
        ("Title", "P1-G2 RC02 inactive activity native matrix"),
        ("ScheduleFromStart", "1"), ("StartDate", start.isoformat()),
        ("FinishDate", (start + timedelta(days=10)).isoformat()),
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
        ("UID", "1"), ("GUID", "22222222-2222-4222-8222-222222222222"),
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
            ("UID", uid), ("GUID", f"00000000-0000-4000-8000-{uid:012d}"),
            ("ID", uid), ("Name", name), ("Active", "1" if active else "0"),
            ("Manual", "0"), ("Type", "1"), ("IsNull", "0"),
            ("CreateDate", "2026-09-24T08:00:00"), ("WBS", uid),
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

    task(1, "RC02-FINISH-DRIVER", 240)

    task(2, "RC02-A-A-PRED", 48)
    task(3, "RC02-A-A-MID", 72, (2,))
    task(4, "RC02-A-A-SUCC", 24, (3,))
    task(5, "RC02-A-I-PRED", 48)
    task(6, "RC02-A-I-MID", 72, (5,), active=False)
    task(7, "RC02-A-I-SUCC", 24, (6,))

    task(8, "RC02-B-A-PRED", 72)
    task(9, "RC02-B-A-MID", 48, (8,))
    task(10, "RC02-B-A-OTHER", 24)
    task(11, "RC02-B-A-SUCC", 24, (9, 10))
    task(12, "RC02-B-I-PRED", 72)
    task(13, "RC02-B-I-MID", 48, (12,), active=False)
    task(14, "RC02-B-I-OTHER", 24)
    task(15, "RC02-B-I-SUCC", 24, (13, 14))

    task(16, "RC02-C-A-PRED", 24)
    task(17, "RC02-C-A-MID", 48, (16,))
    task(18, "RC02-C-A-OTHER", 96)
    task(19, "RC02-C-A-SUCC", 24, (17, 18))
    task(20, "RC02-C-I-PRED", 24, free_slack=pair_c_inactive_pred_free_slack)
    task(21, "RC02-C-I-MID", 48, (20,), active=False)
    task(22, "RC02-C-I-OTHER", 96)
    task(23, "RC02-C-I-SUCC", 24, (21, 22))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_free_slack_sentinel_fixture() -> bytes:
    """Return the one-field UID20 Free-Slack sentinel input."""
    return build_fixture(pair_c_inactive_pred_free_slack=SENTINEL_FREE_SLACK)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--free-slack-sentinel", action="store_true")
    args = parser.parse_args()
    payload = (
        build_free_slack_sentinel_fixture()
        if args.free_slack_sentinel
        else build_fixture()
    )
    args.output.write_bytes(payload)
    print(json.dumps({
        "path": str(args.output),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
