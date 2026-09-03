"""From the canonical calendar model to sorted working intervals over a horizon.

Inheritance, exceptions and special days are all resolved here, once, into
integer intervals; nothing downstream knows a calendar has a base or a holiday.
That is what makes the reference arithmetic reusable verbatim (ADR-002's
model, the design's A.0 calendar decision), and it is where the previous
engine's largest exclusion is paid: it refused any calendar with an exception
inside the horizon, which on a real shutdown was every calendar that mattered.

Rules, in the order they apply:

1. A calendar inherits its base's weekly pattern and exception days.
2. Its own weekdays (1 = Sunday .. 7 = Saturday) override the inherited day.
   A top-level calendar must define all seven.
3. Its own exceptions override inherited exception days for the same date.
   An exception is a date range with a recurrence: every ``period`` days,
   ``occurrences`` times when entered by occurrences, else every ``period``
   days across the range. Only the daily recurrence family is supported;
   any other recurrence type fails the compile with a code rather than
   guessing a pattern. Legacy special days (``DayType 0``) arrive as
   exceptions already, from the migration.
4. For each date in the horizon, the day's intervals are the exception's if
   one applies, else the weekday's; they are clipped to the horizon and
   expressed as seconds from the epoch.

Failure is by code, never by silently producing a different calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sto.core.hashing import canonical_sha256
from sto.core.model.entities import Calendar, CalendarException, Schedule, TimeInterval

from .arithmetic import CompiledIntervals, Intervals

#: Wall-clock naive datetimes, half-open: work in ``[start, finish)`` counts.
Horizon = tuple[datetime, datetime]

SECONDS_PER_DAY = 86400
SUPPORTED_RECURRENCE_TYPES = frozenset({"1", "7"})  # daily; daily every N days


class CalendarCompileError(ValueError):
    """A calendar that cannot be compiled, and why, by code."""

    def __init__(self, code: str, calendar_uid: UUID | None, detail: str = "") -> None:
        self.code = code
        self.calendar_uid = calendar_uid
        self.detail = detail
        super().__init__(f"{code} {calendar_uid}{': ' + detail if detail else ''}")


@dataclass(frozen=True, slots=True)
class CompiledCalendar:
    uid: UUID
    epoch: datetime
    horizon: tuple[int, int]
    intervals: CompiledIntervals
    fingerprint: str
    lineage: tuple[UUID, ...]
    exception_days_applied: int
    exception_days_outside_horizon: int

    def to_seconds(self, moment: datetime) -> int:
        return int((moment - self.epoch).total_seconds())

    def to_datetime(self, coordinate: int) -> datetime:
        return self.epoch + timedelta(seconds=coordinate)


# --- pattern resolution ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Pattern:
    week: dict[int, Intervals]
    exception_days: dict[date, Intervals]
    lineage: tuple[UUID, ...]
    outside: int


def _validate_intervals(
    raw: tuple[TimeInterval, ...], calendar_uid: UUID, where: str
) -> Intervals:
    """The legacy resolver's rules, kept: they were fail-closed for a reason."""

    out: list[tuple[int, int]] = []
    for interval in raw:
        start, finish = int(interval.start_second), int(interval.finish_second)
        if finish == 0:
            finish = SECONDS_PER_DAY
        if start == finish:
            raise CalendarCompileError(
                "CALENDAR_INTERVAL_INVALID",
                calendar_uid,
                f"{where}: equal endpoints {start} are ambiguous",
            )
        if finish < start:
            raise CalendarCompileError(
                "CALENDAR_INTERVAL_INVALID",
                calendar_uid,
                f"{where}: interval {start}-{finish} crosses midnight",
            )
        if not (0 <= start < SECONDS_PER_DAY and 0 < finish <= SECONDS_PER_DAY):
            raise CalendarCompileError(
                "CALENDAR_INTERVAL_INVALID", calendar_uid, f"{where}: {start}-{finish} outside a day"
            )
        out.append((start, finish))
    out.sort()
    merged: list[tuple[int, int]] = []
    for start, finish in out:
        if merged and start < merged[-1][1]:
            raise CalendarCompileError(
                "CALENDAR_INTERVAL_INVALID", calendar_uid, f"{where}: intervals overlap"
            )
        if merged and start == merged[-1][1]:
            merged[-1] = (merged[-1][0], finish)
        else:
            merged.append((start, finish))
    return tuple(merged)


def _exception_dates(
    exception: CalendarException, calendar_uid: UUID
) -> list[date]:
    recurrence = exception.recurrence or {}
    kind = recurrence.get("type", "1")
    if kind not in SUPPORTED_RECURRENCE_TYPES:
        raise CalendarCompileError(
            "CALENDAR_EXCEPTION_RECURRENCE_UNSUPPORTED",
            calendar_uid,
            f"{exception.name or '?'}: recurrence type {kind}",
        )
    first = exception.from_date.date()
    last = exception.to_date.date()
    if last < first:
        raise CalendarCompileError(
            "CALENDAR_EXCEPTION_RANGE_INVALID", calendar_uid, exception.name or ""
        )
    period = int(recurrence.get("period") or 1)
    if period < 1:
        raise CalendarCompileError(
            "CALENDAR_EXCEPTION_RANGE_INVALID", calendar_uid, f"period {period}"
        )
    if recurrence.get("entered_by_occurrences") == "1":
        count = int(recurrence.get("occurrences") or 1)
        dates = [first + timedelta(days=k * period) for k in range(count)]
        if dates and dates[-1] > last:
            raise CalendarCompileError(
                "CALENDAR_EXCEPTION_RANGE_INVALID",
                calendar_uid,
                f"{exception.name or '?'}: {count} occurrences every {period} days "
                f"overrun {last.isoformat()}",
            )
        return dates
    dates = []
    cursor = first
    while cursor <= last:
        dates.append(cursor)
        cursor += timedelta(days=period)
    return dates


class _Resolver:
    def __init__(self, calendars: dict[UUID, Calendar], horizon: Horizon) -> None:
        self._calendars = calendars
        self._first = horizon[0].date()
        self._last = (horizon[1] - timedelta(microseconds=1)).date()
        self._cache: dict[UUID, _Pattern] = {}
        self._active: set[UUID] = set()

    def resolve(self, uid: UUID) -> _Pattern:
        if uid in self._cache:
            return self._cache[uid]
        if uid in self._active:
            raise CalendarCompileError("CALENDAR_INHERITANCE_CYCLE", uid)
        calendar = self._calendars.get(uid)
        if calendar is None:
            raise CalendarCompileError("CALENDAR_NOT_FOUND", uid)
        self._active.add(uid)
        try:
            pattern = self._resolve(calendar)
        finally:
            self._active.discard(uid)
        self._cache[uid] = pattern
        return pattern

    def _resolve(self, calendar: Calendar) -> _Pattern:
        if calendar.base_uid is not None:
            base = self.resolve(calendar.base_uid)
            week = dict(base.week)
            days = dict(base.exception_days)
            lineage = base.lineage
            outside = base.outside
        else:
            week, days, lineage, outside = {}, {}, (), 0

        seen: set[int] = set()
        for weekday in calendar.week:
            if weekday.day not in range(1, 8):
                raise CalendarCompileError(
                    "CALENDAR_WEEKDAY_INVALID", calendar.uid, f"day {weekday.day}"
                )
            if weekday.day in seen:
                raise CalendarCompileError(
                    "CALENDAR_DUPLICATE_WEEKDAY", calendar.uid, f"day {weekday.day}"
                )
            seen.add(weekday.day)
            if weekday.working:
                intervals = _validate_intervals(weekday.intervals, calendar.uid, f"day {weekday.day}")
                if not intervals:
                    raise CalendarCompileError(
                        "CALENDAR_WORKING_DAY_EMPTY", calendar.uid, f"day {weekday.day}"
                    )
                week[weekday.day] = intervals
            else:
                if weekday.intervals:
                    raise CalendarCompileError(
                        "CALENDAR_NONWORKING_DAY_HAS_INTERVALS", calendar.uid, f"day {weekday.day}"
                    )
                week[weekday.day] = ()
        if set(week) != set(range(1, 8)):
            raise CalendarCompileError(
                "CALENDAR_WEEK_INCOMPLETE",
                calendar.uid,
                f"days defined: {sorted(week)}",
            )

        for exception in calendar.exceptions:
            intervals: Intervals = ()
            if exception.working:
                intervals = _validate_intervals(
                    exception.intervals, calendar.uid, exception.name or "exception"
                )
                if not intervals:
                    raise CalendarCompileError(
                        "CALENDAR_WORKING_EXCEPTION_EMPTY", calendar.uid, exception.name or ""
                    )
            for day in _exception_dates(exception, calendar.uid):
                if self._first <= day <= self._last:
                    days[day] = intervals
                else:
                    outside += 1
        return _Pattern(week, days, (*lineage, calendar.uid), outside)


# --- compilation ------------------------------------------------------------------


def _day_type(day: date) -> int:
    """MSPDI weekday numbering: Sunday = 1 .. Saturday = 7."""

    return ((day.weekday() + 1) % 7) + 1


def compile_calendar(
    schedule: Schedule,
    uid: UUID,
    horizon: Horizon,
    *,
    epoch: datetime | None = None,
    _resolver: _Resolver | None = None,
) -> CompiledCalendar:
    start, finish = horizon
    if finish <= start:
        raise CalendarCompileError("CALENDAR_HORIZON_INVALID", uid, f"{start} .. {finish}")
    epoch = epoch or start.replace(hour=0, minute=0, second=0, microsecond=0)
    resolver = _resolver or _Resolver(schedule.calendar_by_uid(), horizon)
    pattern = resolver.resolve(uid)

    horizon_s = (int((start - epoch).total_seconds()), int((finish - epoch).total_seconds()))
    raw: list[tuple[int, int]] = []
    day = start.date()
    last = (finish - timedelta(microseconds=1)).date()
    applied = 0
    while day <= last:
        if day in pattern.exception_days:
            intervals = pattern.exception_days[day]
            applied += 1
        else:
            intervals = pattern.week[_day_type(day)]
        midnight = int((datetime(day.year, day.month, day.day) - epoch).total_seconds())
        for s, f in intervals:
            lo = max(midnight + s, horizon_s[0])
            hi = min(midnight + f, horizon_s[1])
            if lo < hi:
                raw.append((lo, hi))
        day += timedelta(days=1)

    compiled = CompiledIntervals.of(raw)
    payload: dict[str, Any] = {
        "epoch": epoch.isoformat(),
        "horizon": list(horizon_s),
        "intervals": [list(pair) for pair in compiled.intervals],
    }
    return CompiledCalendar(
        uid=uid,
        epoch=epoch,
        horizon=horizon_s,
        intervals=compiled,
        fingerprint=canonical_sha256(payload),
        lineage=pattern.lineage,
        exception_days_applied=applied,
        exception_days_outside_horizon=pattern.outside,
    )


def compile_calendars(
    schedule: Schedule, horizon: Horizon, *, epoch: datetime | None = None
) -> dict[UUID, CompiledCalendar]:
    """Every calendar in the schedule, sharing one resolver and one epoch."""

    start = horizon[0]
    epoch = epoch or start.replace(hour=0, minute=0, second=0, microsecond=0)
    resolver = _Resolver(schedule.calendar_by_uid(), horizon)
    return {
        calendar.uid: compile_calendar(
            schedule, calendar.uid, horizon, epoch=epoch, _resolver=resolver
        )
        for calendar in schedule.calendars
    }
