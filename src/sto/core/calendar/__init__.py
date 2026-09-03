"""Working-time calendars, compiled to intervals and reasoned about in integers.

A calendar in the canonical model is a weekly pattern plus dated exceptions
plus a base it inherits from. The engine cannot use that shape directly: every
question it asks -- when does work starting here finish, how much working time
lies between these two coordinates -- is a question about a sorted list of
half-open working intervals over a horizon. :mod:`compile` produces that list;
:mod:`arithmetic` answers the questions in O(log n).
"""

from .arithmetic import (
    CompiledIntervals,
    add_working,
    consume_duration,
    contains_coordinate,
    earliest_span,
    intersect_intervals,
    next_working,
    prev_working,
    productive_segments,
    shift_working_time,
    sub_working,
    working_between,
)
from .compile import (
    CalendarCompileError,
    CompiledCalendar,
    Horizon,
    compile_calendar,
    compile_calendars,
)

__all__ = [
    "CalendarCompileError",
    "CompiledCalendar",
    "CompiledIntervals",
    "Horizon",
    "add_working",
    "compile_calendar",
    "compile_calendars",
    "consume_duration",
    "contains_coordinate",
    "earliest_span",
    "intersect_intervals",
    "next_working",
    "prev_working",
    "productive_segments",
    "shift_working_time",
    "sub_working",
    "working_between",
]
