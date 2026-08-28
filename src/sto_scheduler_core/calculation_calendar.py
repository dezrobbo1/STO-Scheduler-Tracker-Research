from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .calculation_common import (
    CalculationProfileError,
    CalendarResolutionError,
    _parse_datetime,
)
from .provenance import canonical_sha256


@dataclass(frozen=True, slots=True)
class ResolvedCalendar:
    source_ref: str
    pattern: tuple[tuple[int, tuple[tuple[int, int], ...]], ...]
    source_lineage: tuple[str, ...]
    ignored_exception_count: int

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(_pattern_payload(self.pattern))

    @property
    def effective_id(self) -> str:
        return f"effective-calendar:{self.fingerprint}"


def _pattern_payload(
    pattern: tuple[tuple[int, tuple[tuple[int, int], ...]], ...]
) -> list[dict[str, Any]]:
    return [
        {
            "day_type": day_type,
            "intervals": [
                {"start_second": start, "finish_second": finish}
                for start, finish in intervals
            ],
        }
        for day_type, intervals in pattern
    ]


def _clock_seconds(value: str | None) -> int:
    if not value:
        raise ValueError("missing time")
    parsed = datetime.strptime(value, "%H:%M:%S")
    return parsed.hour * 3600 + parsed.minute * 60 + parsed.second


def _normalize_intervals(
    values: list[dict[str, str | None]],
) -> tuple[tuple[int, int], ...]:
    intervals: list[tuple[int, int]] = []
    for value in values:
        start = _clock_seconds(value.get("from"))
        finish = _clock_seconds(value.get("to"))
        if start == finish == 0:
            # The bounded profile recognizes only the explicit midnight-to-midnight
            # representation as a full-day interval. Other equal endpoints are
            # ambiguous and must fail closed until independently verified.
            intervals.append((0, 86400))
        elif start == finish:
            raise ValueError(
                "equal non-midnight working interval endpoints are ambiguous"
            )
        elif finish > start:
            intervals.append((start, finish))
        elif finish == 0:
            intervals.append((start, 86400))
        else:
            raise ValueError(
                "cross-midnight intervals ending after midnight are unsupported"
            )
    intervals.sort()
    normalized: list[tuple[int, int]] = []
    for start, finish in intervals:
        if finish <= start:
            raise ValueError("working interval must have positive length")
        if normalized and start < normalized[-1][1]:
            raise ValueError("working intervals overlap")
        if normalized and start == normalized[-1][1]:
            normalized[-1] = (normalized[-1][0], finish)
        else:
            normalized.append((start, finish))
    return tuple(normalized)


class _CalendarResolver:
    def __init__(self, document: dict[str, Any]):
        self._calendars = {item["id"]: item for item in document["calendars"]}
        try:
            self._horizon_start = _parse_datetime(document["project"].get("start"))
            self._horizon_finish = _parse_datetime(document["project"].get("finish"))
        except ValueError as exc:
            raise CalculationProfileError(
                f"Project start/finish are required as timezone-naive ISO datetimes: {exc}"
            ) from exc
        if self._horizon_finish < self._horizon_start:
            raise CalculationProfileError("Project finish precedes project start")
        self._cache: dict[str, ResolvedCalendar] = {}
        self._active: set[str] = set()

    def resolve(self, calendar_ref: str | None) -> ResolvedCalendar:
        if calendar_ref is None:
            raise CalendarResolutionError("CALENDAR_REFERENCE_MISSING", calendar_ref)
        if calendar_ref in self._cache:
            return self._cache[calendar_ref]
        if calendar_ref in self._active:
            raise CalendarResolutionError("CALENDAR_INHERITANCE_CYCLE", calendar_ref)
        source = self._calendars.get(calendar_ref)
        if source is None:
            raise CalendarResolutionError("CALENDAR_NOT_FOUND", calendar_ref)

        self._active.add(calendar_ref)
        try:
            base_ref = source.get("base_calendar_ref")
            if base_ref is not None:
                base = self.resolve(base_ref)
                week = dict(base.pattern)
                lineage = list(base.source_lineage)
                ignored_exception_count = base.ignored_exception_count
            else:
                week = {}
                lineage = []
                ignored_exception_count = 0

            regular_days = [
                day
                for day in source.get("week_days", [])
                if day.get("day_type") in range(1, 8)
            ]
            day_types = [day["day_type"] for day in regular_days]
            if len(day_types) != len(set(day_types)):
                raise CalendarResolutionError(
                    "CALENDAR_DUPLICATE_WEEKDAY", calendar_ref
                )
            for day in regular_days:
                day_type = day["day_type"]
                working = day.get("working")
                if working is None:
                    raise CalendarResolutionError(
                        "CALENDAR_DAY_STATE_MISSING", calendar_ref, str(day_type)
                    )
                if working:
                    try:
                        intervals = _normalize_intervals(day.get("working_times", []))
                    except ValueError as exc:
                        raise CalendarResolutionError(
                            "CALENDAR_INTERVAL_INVALID",
                            calendar_ref,
                            f"day {day_type}: {exc}",
                        ) from exc
                    if not intervals:
                        raise CalendarResolutionError(
                            "CALENDAR_WORKING_DAY_EMPTY", calendar_ref, str(day_type)
                        )
                    week[day_type] = intervals
                else:
                    if day.get("working_times"):
                        raise CalendarResolutionError(
                            "CALENDAR_NONWORKING_DAY_HAS_INTERVALS",
                            calendar_ref,
                            str(day_type),
                        )
                    week[day_type] = ()

            if set(week) != set(range(1, 8)):
                raise CalendarResolutionError(
                    "CALENDAR_WEEK_INCOMPLETE", calendar_ref
                )

            for special_day in (
                day
                for day in source.get("week_days", [])
                if day.get("day_type") not in range(1, 8)
            ):
                periods = [
                    extension
                    for extension in special_day.get("extensions", [])
                    if extension.get("name") == "TimePeriod"
                ]
                if len(periods) != 1:
                    raise CalendarResolutionError(
                        "CALENDAR_SPECIAL_DAY_UNRESOLVED", calendar_ref
                    )
                children = {
                    child.get("name"): child.get("text")
                    for child in periods[0].get("children", [])
                }
                try:
                    special_start = _parse_datetime(children.get("FromDate"))
                    special_finish = _parse_datetime(children.get("ToDate"))
                except ValueError as exc:
                    raise CalendarResolutionError(
                        "CALENDAR_SPECIAL_DAY_DATE_INVALID", calendar_ref, str(exc)
                    ) from exc
                if special_finish < special_start:
                    raise CalendarResolutionError(
                        "CALENDAR_SPECIAL_DAY_RANGE_INVALID", calendar_ref
                    )
                if not (
                    special_finish < self._horizon_start
                    or special_start > self._horizon_finish
                ):
                    raise CalendarResolutionError(
                        "CALENDAR_SPECIAL_DAY_OVERLAPS_HORIZON", calendar_ref
                    )
                ignored_exception_count += 1

            for exception in source.get("exceptions", []):
                try:
                    exception_start = _parse_datetime(exception.get("from"))
                    exception_finish = _parse_datetime(exception.get("to"))
                except ValueError as exc:
                    raise CalendarResolutionError(
                        "CALENDAR_EXCEPTION_DATE_INVALID", calendar_ref, str(exc)
                    ) from exc
                if exception_finish < exception_start:
                    raise CalendarResolutionError(
                        "CALENDAR_EXCEPTION_RANGE_INVALID", calendar_ref
                    )
                if not (
                    exception_finish < self._horizon_start
                    or exception_start > self._horizon_finish
                ):
                    raise CalendarResolutionError(
                        "CALENDAR_EXCEPTION_OVERLAPS_HORIZON",
                        calendar_ref,
                        exception.get("id"),
                    )
                ignored_exception_count += 1

            lineage.append(calendar_ref)
            resolved = ResolvedCalendar(
                source_ref=calendar_ref,
                pattern=tuple((day, tuple(week[day])) for day in range(1, 8)),
                source_lineage=tuple(lineage),
                ignored_exception_count=ignored_exception_count,
            )
            self._cache[calendar_ref] = resolved
            return resolved
        finally:
            self._active.discard(calendar_ref)


def _intersect_patterns(
    left: tuple[tuple[int, tuple[tuple[int, int], ...]], ...],
    right: tuple[tuple[int, tuple[tuple[int, int], ...]], ...],
) -> tuple[tuple[int, tuple[tuple[int, int], ...]], ...]:
    left_by_day = dict(left)
    right_by_day = dict(right)
    result: list[tuple[int, tuple[tuple[int, int], ...]]] = []
    for day_type in range(1, 8):
        intersections: list[tuple[int, int]] = []
        for left_start, left_finish in left_by_day[day_type]:
            for right_start, right_finish in right_by_day[day_type]:
                start = max(left_start, right_start)
                finish = min(left_finish, right_finish)
                if start < finish:
                    intersections.append((start, finish))
        intersections.sort()
        result.append((day_type, tuple(intersections)))
    return tuple(result)


def _day_type(value: datetime) -> int:
    # MSPDI DayType: Sunday=1, Monday=2, ..., Saturday=7.
    return ((value.weekday() + 1) % 7) + 1


def _second_of_day(value: datetime) -> int:
    return value.hour * 3600 + value.minute * 60 + value.second


def _at_second(value: datetime, second: int) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        seconds=second
    )


def _next_working_time(
    value: datetime,
    pattern: tuple[tuple[int, tuple[tuple[int, int], ...]], ...],
) -> datetime:
    by_day = dict(pattern)
    current = value
    for _ in range(10000):
        second = _second_of_day(current)
        for start, finish in by_day[_day_type(current)]:
            if second < finish:
                return _at_second(current, max(second, start))
        current = current.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
    raise CalculationProfileError("Calendar search exceeded bounded horizon")


def _add_working_seconds(
    value: datetime,
    seconds: int | float,
    pattern: tuple[tuple[int, tuple[tuple[int, int], ...]], ...],
) -> datetime:
    if seconds < 0:
        raise CalculationProfileError("Negative duration is unsupported")
    if seconds == 0:
        return value
    current = _next_working_time(value, pattern)
    remaining = float(seconds)
    by_day = dict(pattern)
    for _ in range(10000):
        second = _second_of_day(current)
        for start, finish in by_day[_day_type(current)]:
            if second >= finish:
                continue
            work_start = max(second, start)
            available = finish - work_start
            if remaining <= available:
                return _at_second(current, int(work_start + remaining))
            remaining -= available
            second = finish
        current = current.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        current = _next_working_time(current, pattern)
    raise CalculationProfileError("Working-time addition exceeded bounded horizon")
