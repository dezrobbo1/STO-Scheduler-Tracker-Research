"""Finite MSPDI source-integrity contract for the measured RC03 float shape.

These are singleton source declarations used to establish eligibility, not a
general XML validation policy. Repeating PredecessorLink, TimephasedData,
WeekDay, WorkingTime, Exception, Baseline and ExtendedAttribute rows remain
valid structures. Ordinary import continues to read its first value.
"""

from __future__ import annotations

from types import MappingProxyType
from xml.etree import ElementTree as ET

from .mspdi_shared import _q


RC03_SINGLETON_FIELDS = MappingProxyType({
    "project": frozenset({"ScheduleFromStart", "StartDate", "CalendarUID"}),
    "task": frozenset({
        "UID", "Summary", "Active", "Manual", "Type", "IsNull", "Milestone",
        "Duration", "DurationFormat", "RemainingDuration", "Work", "RemainingWork",
        "ActualDuration", "ActualWork", "PercentComplete", "PercentWorkComplete",
        "PhysicalPercentComplete", "ActualStart", "ActualFinish", "Stop", "Resume",
        "CalendarUID", "ConstraintType", "ConstraintDate", "Deadline",
        "EffortDriven", "LevelingDelay", "IgnoreResourceCalendar",
    }),
    "relationship": frozenset({
        "PredecessorUID", "Type", "LinkLag", "LagFormat", "CrossProject",
        "CrossProjectName",
    }),
    "assignment": frozenset({
        "UID", "TaskUID", "ResourceUID", "Start", "Finish", "Units", "Work",
        "RemainingWork", "ActualWork", "PercentWorkComplete", "WorkContour",
        "Delay", "LevelingDelay",
    }),
    "resource": frozenset({
        "UID", "Type", "IsNull", "IsGeneric", "IsCostResource", "IsInactive",
        "CalendarUID",
    }),
    "calendar": frozenset({
        "UID", "BaseCalendarUID", "IsBaseCalendar", "WeekDays", "Exceptions",
    }),
    "calendar_weekday": frozenset({"DayType", "DayWorking", "WorkingTimes"}),
    "calendar_working_time": frozenset({"FromTime", "ToTime"}),
    "calendar_exception": frozenset({"Type", "DayWorking", "TimePeriod", "WorkingTimes"}),
    "calendar_time_period": frozenset({"FromDate", "ToDate"}),
})

RC03_REPEATING_FIELDS = frozenset({
    "PredecessorLink", "TimephasedData", "WeekDay", "WorkingTime",
    "Exception", "Baseline", "ExtendedAttribute",
})

# The exact BOILER roots declare ordinary zero-lag FS links with LagFormat 7.
# Unknown values cannot be evidence of that form even if generic migration
# otherwise treats their zero-second lag as a project-policy edge.
RC03_SOURCE_ENUMS = MappingProxyType({
    "project.ScheduleFromStart": frozenset({"1"}),
    "task.Type": frozenset({"0"}),  # fixed units
    "task.Summary": frozenset({"0"}),
    "task.Active": frozenset({"1"}),
    "task.Manual": frozenset({"0"}),
    "task.IsNull": frozenset({"0"}),
    "task.Milestone": frozenset({"0"}),
    "task.DurationFormat": frozenset({"8"}),  # 96 elapsed hours
    "task.ConstraintType": frozenset({"0"}),  # ASAP
    "task.EffortDriven": frozenset({"0"}),
    "task.LevelingDelay": frozenset({"0"}),
    "task.IgnoreResourceCalendar": frozenset({"0"}),
    "resource.Type": frozenset({"1"}),  # labor
    "resource.IsNull": frozenset({"0"}),
    "resource.IsGeneric": frozenset({"0"}),
    "resource.IsCostResource": frozenset({"0"}),
    "resource.IsInactive": frozenset({"0"}),
    "relationship.Type": frozenset({"1"}),  # FS
    "relationship.LinkLag": frozenset({"0"}),
    "relationship.LagFormat": frozenset({"7"}),
    "relationship.CrossProject": frozenset({"0"}),
    "assignment.WorkContour": frozenset({"0"}),
    "assignment.PercentWorkComplete": frozenset({"0"}),
    "assignment.Delay": frozenset({"0"}),
    "assignment.LevelingDelay": frozenset({"0"}),
})


def singleton_ambiguities(element: ET.Element, kind: str) -> frozenset[str]:
    """Return repeated singleton declarations relevant to this RC03 shape."""

    return frozenset(name for name in RC03_SINGLETON_FIELDS[kind]
                     if len(element.findall(_q(name))) > 1)


def calendar_ambiguities(element: ET.Element) -> frozenset[str]:
    """Include source declarations that determine compiled inherited time."""

    issues = set(singleton_ambiguities(element, "calendar"))
    weekdays = element.find(_q("WeekDays"))
    if weekdays is not None:
        for day in weekdays.findall(_q("WeekDay")):
            issues.update(f"WeekDay/{name}" for name in
                          singleton_ambiguities(day, "calendar_weekday"))
            times = day.find(_q("WorkingTimes"))
            if times is not None:
                for span in times.findall(_q("WorkingTime")):
                    issues.update(f"WorkingTime/{name}" for name in
                                  singleton_ambiguities(span, "calendar_working_time"))
    exceptions = element.find(_q("Exceptions"))
    if exceptions is not None:
        for exception in exceptions.findall(_q("Exception")):
            issues.update(f"Exception/{name}" for name in
                          singleton_ambiguities(exception, "calendar_exception"))
            period = exception.find(_q("TimePeriod"))
            if period is not None:
                issues.update(f"TimePeriod/{name}" for name in
                              singleton_ambiguities(period, "calendar_time_period"))
            times = exception.find(_q("WorkingTimes"))
            if times is not None:
                for span in times.findall(_q("WorkingTime")):
                    issues.update(f"WorkingTime/{name}" for name in
                                  singleton_ambiguities(span, "calendar_working_time"))
    return frozenset(issues)


def admitted_source_enum(element: ET.Element, kind: str, name: str) -> bool:
    """Whether a present raw enum declares the measured RC03 meaning."""

    value = element.findtext(_q(name))
    return value is not None and value.strip() in RC03_SOURCE_ENUMS[f"{kind}.{name}"]


def unsupported_source_enums(element: ET.Element, kind: str) -> frozenset[str]:
    """Raw declarations missing or outside the measured RC03 source values."""

    prefix = f"{kind}."
    return frozenset(qualified[len(prefix):] for qualified in RC03_SOURCE_ENUMS
                     if qualified.startswith(prefix)
                     and not admitted_source_enum(element, kind,
                                                  qualified[len(prefix):]))
