"""Integer working-time arithmetic over sorted half-open intervals.

Two layers, deliberately.

The first five functions -- :func:`intersect_intervals`,
:func:`contains_coordinate`, :func:`consume_duration`,
:func:`shift_working_time`, :func:`productive_segments` -- are the reference
implementation from ``dezrobbo1/PM-Software``'s
``deterministic_scheduling_core/calendars/arithmetic.py`` at the pinned commit,
verbatim. The semantic conformance corpus was declared against them, so they
stay as they are and everything else is checked against them.

The second layer is what the engine actually calls. :class:`CompiledIntervals`
carries the same intervals with their start coordinates and cumulative work as
parallel arrays, so :func:`next_working`, :func:`add_working`,
:func:`sub_working` and :func:`working_between` are a bisect and an index --
O(log n) in the number of intervals -- instead of a scan. Each is tested to
agree with the reference on the same inputs.

Coordinates are integer seconds from a per-run epoch. Intervals are
``(start, finish)`` with ``start < finish``, sorted, non-overlapping, and
non-adjacent (adjacent intervals are merged at compile time).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

Intervals = tuple[tuple[int, int], ...]


# --- reference implementation (PM-Software, verbatim) ---------------------------


def intersect_intervals(left: Sequence[Sequence[int]], right: Sequence[Sequence[int]]) -> Intervals:
    result: list[tuple[int, int]] = []
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        start = max(left[left_index][0], right[right_index][0])
        finish = min(left[left_index][1], right[right_index][1])
        if start < finish:
            result.append((start, finish))
        if left[left_index][1] <= right[right_index][1]:
            left_index += 1
        else:
            right_index += 1
    return tuple(result)


def contains_coordinate(coordinate: int, intervals: Sequence[Sequence[int]]) -> bool:
    return any(start <= coordinate < finish for start, finish in intervals)


def consume_duration(
    start: int, duration: int, intervals: Sequence[Sequence[int]]
) -> int | None:
    """Consume productive integer duration from an explicit start coordinate."""

    if duration < 0:
        return None
    if duration == 0:
        return start if contains_coordinate(start, intervals) else None
    if not contains_coordinate(start, intervals):
        return None
    remaining = duration
    cursor = start
    for interval_start, interval_finish in intervals:
        if interval_finish <= cursor:
            continue
        if cursor < interval_start:
            cursor = interval_start
        available = interval_finish - cursor
        if remaining <= available:
            return cursor + remaining
        remaining -= available
        cursor = interval_finish
    return None


def shift_working_time(
    anchor: int, lag: int, intervals: Sequence[Sequence[int]]
) -> int | None:
    """Apply signed productive lag; zero lag preserves its event coordinate."""

    if lag == 0:
        return anchor
    if lag > 0:
        remaining = lag
        cursor = anchor
        for interval_start, interval_finish in intervals:
            if interval_finish <= cursor:
                continue
            position = max(cursor, interval_start)
            available = interval_finish - position
            if remaining <= available:
                return position + remaining
            remaining -= available
            cursor = interval_finish
        return None

    remaining = -lag
    cursor = anchor
    for interval_start, interval_finish in reversed(intervals):
        if interval_start >= cursor:
            continue
        position = min(cursor, interval_finish)
        available = position - interval_start
        if remaining <= available:
            return position - remaining
        remaining -= available
        cursor = interval_start
    return None


def productive_segments(
    start: int, finish: int, intervals: Sequence[Sequence[int]]
) -> tuple[tuple[int, int], ...]:
    segments: list[tuple[int, int]] = []
    for interval_start, interval_finish in intervals:
        segment_start = max(start, interval_start)
        segment_finish = min(finish, interval_finish)
        if segment_start < segment_finish:
            segments.append((segment_start, segment_finish))
    return tuple(segments)


# --- indexed layer ----------------------------------------------------------------


def normalise(intervals: Sequence[Sequence[int]]) -> Intervals:
    """Sort, drop empties, merge overlaps and adjacencies."""

    merged: list[tuple[int, int]] = []
    for start, finish in sorted((int(s), int(f)) for s, f in intervals):
        if finish <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
        else:
            merged.append((start, finish))
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class CompiledIntervals:
    """Intervals with the two arrays that make every query a bisect.

    ``starts[i]`` is the start of interval *i*; ``work_before[i]`` is the
    productive time in all intervals before *i*. Build with :meth:`of`.
    """

    intervals: Intervals
    starts: tuple[int, ...]
    finishes: tuple[int, ...]
    work_before: tuple[int, ...]

    @classmethod
    def of(cls, intervals: Sequence[Sequence[int]]) -> CompiledIntervals:
        clean = normalise(intervals)
        starts = tuple(s for s, _ in clean)
        finishes = tuple(f for _, f in clean)
        before: list[int] = []
        total = 0
        for start, finish in clean:
            before.append(total)
            total += finish - start
        return cls(clean, starts, finishes, tuple(before))

    @property
    def total_work(self) -> int:
        if not self.intervals:
            return 0
        return self.work_before[-1] + (self.finishes[-1] - self.starts[-1])

    @property
    def first(self) -> int | None:
        return self.starts[0] if self.starts else None

    @property
    def last(self) -> int | None:
        return self.finishes[-1] if self.finishes else None

    def index_at(self, coordinate: int) -> int:
        """Index of the interval containing ``coordinate``, else -1."""

        i = bisect_right(self.starts, coordinate) - 1
        if i >= 0 and coordinate < self.finishes[i]:
            return i
        return -1

    def work_until(self, coordinate: int) -> int:
        """Productive time from the first interval start up to ``coordinate``."""

        i = bisect_right(self.starts, coordinate) - 1
        if i < 0:
            return 0
        return self.work_before[i] + min(coordinate, self.finishes[i]) - self.starts[i]


def next_working(calendar: CompiledIntervals, coordinate: int) -> int | None:
    """The smallest working coordinate at or after ``coordinate``."""

    i = calendar.index_at(coordinate)
    if i >= 0:
        return coordinate
    j = bisect_right(calendar.starts, coordinate)
    return calendar.starts[j] if j < len(calendar.starts) else None


def prev_working(calendar: CompiledIntervals, coordinate: int) -> int | None:
    """The largest coordinate at or before ``coordinate`` at which work can finish.

    A finish coordinate lies in ``(start, finish]`` of some interval, so an
    interval's own finish edge is a valid answer while its start edge is not.
    """

    i = bisect_right(calendar.starts, coordinate) - 1
    while i >= 0:
        start, finish = calendar.starts[i], calendar.finishes[i]
        if coordinate > start:
            return min(coordinate, finish)
        i -= 1
    return None


def add_working(calendar: CompiledIntervals, coordinate: int, duration: int) -> int | None:
    """``duration`` seconds of work after ``coordinate``; the same event coordinate for zero.

    Work is measured from the next working coordinate, so a start that falls in
    a gap begins at the following interval. Agrees with
    :func:`shift_working_time` for positive lag on every input.
    """

    if duration < 0:
        raise ValueError("duration must be non-negative")
    if duration == 0:
        return coordinate
    origin = next_working(calendar, coordinate)
    if origin is None:
        return None
    target = calendar.work_until(origin) + duration
    if target > calendar.total_work:
        return None
    # The interval in which cumulative work reaches ``target``: the last one
    # whose work_before is strictly below it.
    i = bisect_left(calendar.work_before, target) - 1
    if i < 0:
        i = 0
    return calendar.starts[i] + (target - calendar.work_before[i])


def sub_working(calendar: CompiledIntervals, coordinate: int, duration: int) -> int | None:
    """``duration`` seconds of work before ``coordinate``. Mirror of :func:`add_working`.

    Agrees with :func:`shift_working_time` for negative lag on every input.
    """

    if duration < 0:
        raise ValueError("duration must be non-negative")
    if duration == 0:
        return coordinate
    origin = prev_working(calendar, coordinate)
    if origin is None:
        return None
    target = calendar.work_until(origin) - duration
    if target < 0:
        return None
    i = bisect_right(calendar.work_before, target) - 1
    if i < 0:
        return None
    return calendar.starts[i] + (target - calendar.work_before[i])


def working_between(calendar: CompiledIntervals, start: int, finish: int) -> int:
    """Productive seconds in ``[start, finish)``."""

    if finish <= start:
        return 0
    return calendar.work_until(finish) - calendar.work_until(start)


def earliest_span(
    calendar: CompiledIntervals,
    start_lower_bound: int,
    finish_lower_bound: int,
    duration: int,
    horizon: int,
) -> tuple[int, int] | None:
    """The lexicographically earliest span with start ≥ one bound and finish ≥ the other.

    The reference scans every integer coordinate. This finds the same span by
    monotonicity: the finish is non-decreasing in the start, so the answer is
    the earliest start whose finish reaches ``finish_lower_bound``, if the
    plain earliest start does not already.
    """

    if duration < 0:
        return None
    lower = max(0, start_lower_bound)
    if duration == 0:
        start = next_working(calendar, max(lower, finish_lower_bound))
        if start is None or start > horizon:
            return None
        return start, start
    start = next_working(calendar, lower)
    if start is None:
        return None
    finish = add_working(calendar, start, duration)
    if finish is None:
        return None
    if finish < finish_lower_bound:
        # The smallest achievable finish at or beyond the bound: the bound
        # itself when it lies in some (start, finish], else one second into the
        # next interval -- a finish can only land inside an interval.
        i = bisect_right(calendar.starts, finish_lower_bound) - 1
        if i >= 0 and calendar.starts[i] < finish_lower_bound <= calendar.finishes[i]:
            reach = finish_lower_bound
        else:
            # bisect_left: a bound that equals an interval's start belongs to
            # that interval, and its first reachable finish is one second in.
            j = bisect_left(calendar.starts, finish_lower_bound)
            if j >= len(calendar.starts):
                return None
            reach = calendar.starts[j] + 1
        start = sub_working(calendar, reach, duration)
        if start is None or start < lower:
            return None
        # sub_working may return an interval's finish edge; work starts at the next start.
        start = next_working(calendar, start)
        if start is None:
            return None
        finish = add_working(calendar, start, duration)
        if finish is None:
            return None
    if finish > horizon:
        return None
    return start, finish
