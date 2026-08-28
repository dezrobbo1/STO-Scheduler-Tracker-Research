from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

PROFILE_VERSION = "mspdi-calculation-eligibility-v0.2"
SUPPORTED_SCHEMA_VERSION = "0.1.1"
SUPPORTED_IMPORTER_PROFILE = "mspdi-import-v0.1.1"
SUPPORTED_CONSTRAINT_TYPES = {0: "ASAP"}
SUPPORTED_RELATIONSHIP_TYPES = {"FS"}
SUPPORTED_DURATION_FORMATS = {"5"}
SUPPORTED_NEGATIVE_ELAPSED_LAG_FORMAT = 8

REASON_PRIORITY = (
    "PROJECT_SCHEDULE_DIRECTION_UNSUPPORTED",
    "ACTIVITY_INACTIVE",
    "ACTIVITY_MANUAL",
    "ACTIVITY_NULL",
    "TASK_TYPE_UNSUPPORTED",
    "ESTIMATED_DURATION_UNSUPPORTED",
    "DURATION_MISSING",
    "DURATION_UNPARSED",
    "DURATION_NEGATIVE",
    "DURATION_FORMAT_UNSUPPORTED",
    "MILESTONE_DURATION_MISMATCH",
    "SOURCE_COORDINATE_MISSING",
    "SOURCE_DATETIME_UNSUPPORTED",
    "PROGRESS_STATE_PRESENT",
    "ACTUAL_STATE_PRESENT",
    "REMAINING_DURATION_MISMATCH",
    "REMAINING_WORK_MISMATCH",
    "DEADLINE_PRESENT",
    "CONSTRAINT_UNSUPPORTED",
    "CONSTRAINT_DATE_UNEXPECTED",
    "EFFORT_DRIVEN_UNSUPPORTED",
    "RECURRING_TASK_UNSUPPORTED",
    "EXTERNAL_TASK_UNSUPPORTED",
    "SUBPROJECT_TASK_UNSUPPORTED",
    "LEVELING_DELAY_UNSUPPORTED",
    "IGNORE_RESOURCE_CALENDAR_FLAG_UNRESOLVED",
    "IGNORE_RESOURCE_CALENDAR_WITHOUT_TASK_CALENDAR_UNSUPPORTED",
    "TASK_CALENDAR_UNRESOLVED",
    "RESOURCE_CALENDAR_UNRESOLVED",
    "RESOURCE_INACTIVE_UNSUPPORTED",
    "MULTIPLE_RESOURCE_CALENDARS_UNSUPPORTED",
    "EMPTY_EFFECTIVE_CALENDAR",
    "ASSIGNMENT_PROGRESS_STATE_PRESENT",
    "ASSIGNMENT_CONTOUR_UNSUPPORTED",
    "WORK_UNITS_INCONSISTENT",
    "SOURCE_START_OUTSIDE_WORKING_TIME",
    "SOURCE_SPAN_MISMATCH",
    "RELATIONSHIP_ENDPOINT_UNSUPPORTED",
    "RELATIONSHIP_TYPE_UNSUPPORTED",
    "RELATIONSHIP_LAG_UNSUPPORTED",
    "CROSS_PROJECT_RELATIONSHIP_UNSUPPORTED",
    "RELATIONSHIP_EXTENSION_UNSUPPORTED",
    "INELIGIBLE_PREDECESSOR",
)


class CalculationProfileError(ValueError):
    pass


class CalendarResolutionError(CalculationProfileError):
    def __init__(self, code: str, calendar_ref: str | None, detail: str | None = None):
        self.code = code
        self.calendar_ref = calendar_ref
        self.detail = detail
        suffix = f": {detail}" if detail else ""
        super().__init__(f"{code} ({calendar_ref!r}){suffix}")


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        raise ValueError("missing datetime")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("timezone-aware datetimes are outside the bounded calculation profile")
    return parsed


def _duration_seconds(value: dict[str, Any] | None) -> int | float | None:
    if not value or value.get("parse_status") != "parsed":
        return None
    seconds = value.get("seconds")
    return seconds if isinstance(seconds, (int, float)) else None


def _first_reason(reason_codes: Iterable[str]) -> str:
    reason_set = set(reason_codes)
    for reason in REASON_PRIORITY:
        if reason in reason_set:
            return reason
    return sorted(reason_set)[0]
