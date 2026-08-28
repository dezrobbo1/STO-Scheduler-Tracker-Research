from __future__ import annotations

from collections import defaultdict
from typing import Any

from .calculation_calendar import (
    ResolvedCalendar,
    _CalendarResolver,
    _add_working_seconds,
    _intersect_patterns,
    _next_working_time,
)
from .calculation_common import (
    SUPPORTED_CONSTRAINT_TYPES,
    SUPPORTED_DURATION_FORMATS,
    CalendarResolutionError,
    _duration_seconds,
    _parse_datetime,
)


def _extension_values(
    activity: dict[str, Any], extension_by_id: dict[str, dict[str, Any]]
) -> dict[str, list[str | None]]:
    values: dict[str, list[str | None]] = defaultdict(list)
    for ref in activity.get("extension_refs", []):
        extension = extension_by_id.get(ref)
        if extension is None:
            continue
        payload = extension.get("payload", {})
        values[str(payload.get("name"))].append(payload.get("text"))
    return dict(values)


def _one_extension_value(
    values: dict[str, list[str | None]], name: str
) -> str | None:
    candidates = values.get(name, [])
    if len(candidates) != 1:
        return None
    return candidates[0]


def _duration_contains_actual_state(value: dict[str, Any] | None) -> bool:
    """Return True for any non-empty actual duration/work value we cannot prove is zero.

    The calculation profile is fail-closed. Unsupported/unparsed duration text is therefore
    evidence of source state, not equivalent to an absent value.
    """

    if value is None:
        return False
    if value.get("parse_status") != "parsed":
        return True
    seconds = value.get("seconds")
    if not isinstance(seconds, (int, float)):
        return True
    return seconds != 0


def classify_local_activities(document: dict[str, Any]) -> dict[str, Any]:
    _parse_datetime(document["project"].get("start"))
    extension_by_id = {
        item["id"]: item for item in document.get("vendor_extensions", [])
    }
    activity_by_id = {item["id"]: item for item in document["activities"]}
    resource_by_id = {item["id"]: item for item in document["resources"]}
    assignments_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assignment in document["assignments"]:
        assignments_by_task[assignment.get("task_ref")].append(assignment)

    calendar_resolver = _CalendarResolver(document)
    reasons: dict[str, set[str]] = {
        activity_id: set() for activity_id in activity_by_id
    }
    effective_patterns: dict[
        str, tuple[tuple[int, tuple[tuple[int, int], ...]], ...]
    ] = {}
    calendar_lineage: dict[str, tuple[str, ...]] = {}
    ignored_exception_counts: dict[str, int] = {}

    for activity_id, activity in activity_by_id.items():
        activity_reasons = reasons[activity_id]
        extension_values = _extension_values(activity, extension_by_id)

        if activity.get("active") is not True:
            activity_reasons.add("ACTIVITY_INACTIVE")
        if activity.get("manual") is not False:
            activity_reasons.add("ACTIVITY_MANUAL")
        if activity.get("is_null_source") is not False:
            activity_reasons.add("ACTIVITY_NULL")
        if activity.get("source_task_type") != 0:
            activity_reasons.add("TASK_TYPE_UNSUPPORTED")
        if activity.get("estimated") is not False:
            activity_reasons.add("ESTIMATED_DURATION_UNSUPPORTED")

        duration = activity.get("duration")
        if duration is None:
            activity_reasons.add("DURATION_MISSING")
            duration_seconds = None
        elif duration.get("parse_status") != "parsed":
            activity_reasons.add("DURATION_UNPARSED")
            duration_seconds = None
        else:
            duration_seconds = _duration_seconds(duration)
            if duration_seconds is None:
                activity_reasons.add("DURATION_UNPARSED")
            elif duration_seconds < 0:
                activity_reasons.add("DURATION_NEGATIVE")

        duration_format = _one_extension_value(extension_values, "DurationFormat")
        if duration_format not in SUPPORTED_DURATION_FORMATS:
            activity_reasons.add("DURATION_FORMAT_UNSUPPORTED")

        if duration_seconds is not None:
            if bool(activity.get("milestone")) != (duration_seconds == 0):
                activity_reasons.add("MILESTONE_DURATION_MISMATCH")

        try:
            source_start = _parse_datetime(activity.get("start"))
            source_finish = _parse_datetime(activity.get("finish"))
        except ValueError:
            source_start = source_finish = None
            if not activity.get("start") or not activity.get("finish"):
                activity_reasons.add("SOURCE_COORDINATE_MISSING")
            else:
                activity_reasons.add("SOURCE_DATETIME_UNSUPPORTED")

        if any(
            (activity.get(field) or 0) != 0
            for field in (
                "percent_complete_source",
                "percent_work_complete_source",
                "physical_percent_complete_source",
            )
        ):
            activity_reasons.add("PROGRESS_STATE_PRESENT")
        if activity.get("actual_start_source") or activity.get("actual_finish_source"):
            activity_reasons.add("ACTUAL_STATE_PRESENT")
        if _duration_contains_actual_state(activity.get("actual_duration_source")):
            activity_reasons.add("ACTUAL_STATE_PRESENT")
        if _duration_contains_actual_state(activity.get("actual_work_source")):
            activity_reasons.add("ACTUAL_STATE_PRESENT")
        if duration_seconds is not None and _duration_seconds(
            activity.get("remaining_duration_source")
        ) != duration_seconds:
            activity_reasons.add("REMAINING_DURATION_MISMATCH")
        source_work = _duration_seconds(activity.get("work"))
        remaining_work = _duration_seconds(activity.get("remaining_work_source"))
        if source_work is not None and remaining_work != source_work:
            activity_reasons.add("REMAINING_WORK_MISMATCH")

        if activity.get("deadline_source"):
            activity_reasons.add("DEADLINE_PRESENT")
        constraint_type = activity.get("constraint_type_source")
        if constraint_type not in SUPPORTED_CONSTRAINT_TYPES:
            activity_reasons.add("CONSTRAINT_UNSUPPORTED")
        if activity.get("constraint_date_source"):
            activity_reasons.add("CONSTRAINT_DATE_UNEXPECTED")

        if _one_extension_value(extension_values, "EffortDriven") != "0":
            activity_reasons.add("EFFORT_DRIVEN_UNSUPPORTED")
        if _one_extension_value(extension_values, "Recurring") != "0":
            activity_reasons.add("RECURRING_TASK_UNSUPPORTED")
        if _one_extension_value(extension_values, "ExternalTask") != "0":
            activity_reasons.add("EXTERNAL_TASK_UNSUPPORTED")
        if _one_extension_value(extension_values, "IsSubproject") != "0":
            activity_reasons.add("SUBPROJECT_TASK_UNSUPPORTED")
        leveling_delay = _one_extension_value(extension_values, "LevelingDelay")
        if leveling_delay not in (None, "0"):
            activity_reasons.add("LEVELING_DELAY_UNSUPPORTED")

        ignore_resource_calendar = _one_extension_value(
            extension_values, "IgnoreResourceCalendar"
        )
        if ignore_resource_calendar not in {"0", "1"}:
            activity_reasons.add("IGNORE_RESOURCE_CALENDAR_FLAG_UNRESOLVED")

        explicit_task_calendar_ref = activity.get("calendar_ref")
        project_calendar_ref = document["project"].get("calendar_ref")
        task_calendar: ResolvedCalendar | None = None
        task_calendar_ref = explicit_task_calendar_ref or project_calendar_ref
        try:
            task_calendar = calendar_resolver.resolve(task_calendar_ref)
        except CalendarResolutionError:
            activity_reasons.add("TASK_CALENDAR_UNRESOLVED")

        real_assignments: list[dict[str, Any]] = []
        resource_calendars: list[ResolvedCalendar] = []
        for assignment in assignments_by_task.get(activity_id, []):
            resource_ref = assignment.get("resource_ref")
            if resource_ref is None:
                continue
            real_assignments.append(assignment)
            resource = resource_by_id.get(resource_ref)
            if resource is None:
                activity_reasons.add("RESOURCE_CALENDAR_UNRESOLVED")
                continue
            if resource.get("inactive_source") is True:
                activity_reasons.add("RESOURCE_INACTIVE_UNSUPPORTED")
            try:
                resource_calendars.append(
                    calendar_resolver.resolve(resource.get("calendar_ref"))
                )
            except CalendarResolutionError:
                activity_reasons.add("RESOURCE_CALENDAR_UNRESOLVED")

            if (assignment.get("percent_work_complete_source") or 0) != 0:
                activity_reasons.add("ASSIGNMENT_PROGRESS_STATE_PRESENT")
            if _duration_contains_actual_state(assignment.get("actual_work_source")):
                activity_reasons.add("ASSIGNMENT_PROGRESS_STATE_PRESENT")
            assignment_work = _duration_seconds(assignment.get("work_source"))
            assignment_remaining = _duration_seconds(
                assignment.get("remaining_work_source")
            )
            if assignment_work is not None and assignment_remaining != assignment_work:
                activity_reasons.add("ASSIGNMENT_PROGRESS_STATE_PRESENT")
            if assignment.get("work_contour_source") not in (None, 0):
                activity_reasons.add("ASSIGNMENT_CONTOUR_UNSUPPORTED")

        distinct_resource_patterns = {
            calendar.pattern for calendar in resource_calendars
        }
        if ignore_resource_calendar != "1" and len(distinct_resource_patterns) > 1:
            activity_reasons.add("MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED")

        if ignore_resource_calendar == "1" and explicit_task_calendar_ref is None:
            activity_reasons.add(
                "IGNORE_RESOURCE_CALENDAR_WITHOUT_TASK_CALENDAR_UNSUPPORTED"
            )

        if duration_seconds is not None and duration_seconds > 0 and real_assignments:
            total_work = 0.0
            total_units = 0.0
            work_units_valid = True
            for assignment in real_assignments:
                assignment_work = _duration_seconds(assignment.get("work_source"))
                units = assignment.get("units_source")
                if assignment_work is None or not isinstance(units, (int, float)):
                    work_units_valid = False
                    break
                if units <= 0:
                    work_units_valid = False
                    break
                total_work += float(assignment_work)
                total_units += float(units)
            if (
                not work_units_valid
                or total_units <= 0
                or abs(total_work - float(duration_seconds) * total_units) > 1e-6
            ):
                activity_reasons.add("WORK_UNITS_INCONSISTENT")

        effective_pattern = None
        lineage: tuple[str, ...] = ()
        ignored_exception_count = 0
        if task_calendar is not None:
            if explicit_task_calendar_ref is not None:
                if ignore_resource_calendar == "1" or not resource_calendars:
                    effective_pattern = task_calendar.pattern
                    lineage = task_calendar.source_lineage
                    ignored_exception_count = task_calendar.ignored_exception_count
                elif len(distinct_resource_patterns) == 1:
                    resource_calendar = resource_calendars[0]
                    effective_pattern = _intersect_patterns(
                        task_calendar.pattern, resource_calendar.pattern
                    )
                    lineage = tuple(
                        dict.fromkeys(
                            task_calendar.source_lineage
                            + resource_calendar.source_lineage
                        )
                    )
                    ignored_exception_count = (
                        task_calendar.ignored_exception_count
                        + resource_calendar.ignored_exception_count
                    )
            elif resource_calendars and len(distinct_resource_patterns) == 1:
                resource_calendar = resource_calendars[0]
                effective_pattern = resource_calendar.pattern
                lineage = resource_calendar.source_lineage
                ignored_exception_count = resource_calendar.ignored_exception_count
            elif not resource_calendars:
                effective_pattern = task_calendar.pattern
                lineage = task_calendar.source_lineage
                ignored_exception_count = task_calendar.ignored_exception_count

        if effective_pattern is not None:
            if not any(intervals for _, intervals in effective_pattern):
                activity_reasons.add("EMPTY_EFFECTIVE_CALENDAR")
            else:
                effective_patterns[activity_id] = effective_pattern
                calendar_lineage[activity_id] = lineage
                ignored_exception_counts[activity_id] = ignored_exception_count

        if (
            effective_pattern is not None
            and duration_seconds is not None
            and source_start is not None
            and source_finish is not None
        ):
            if duration_seconds == 0:
                calculated_finish = source_start
            else:
                next_start = _next_working_time(source_start, effective_pattern)
                if next_start != source_start:
                    activity_reasons.add("SOURCE_START_OUTSIDE_WORKING_TIME")
                calculated_finish = _add_working_seconds(
                    source_start, duration_seconds, effective_pattern
                )
            if calculated_finish != source_finish:
                activity_reasons.add("SOURCE_SPAN_MISMATCH")

    return {
        "activity_by_id": activity_by_id,
        "reasons": reasons,
        "effective_patterns": effective_patterns,
        "calendar_lineage": calendar_lineage,
        "ignored_exception_counts": ignored_exception_counts,
    }
