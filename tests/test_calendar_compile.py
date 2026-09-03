"""Compiling calendars: inheritance, exceptions, special days, failure by code.

The BOILER cases compile every real calendar and check that a real exception
day is non-working. They compile over 2025, because every exception in that
file falls outside the schedule's 2026 window -- the calendars were carried
from a template -- which is itself a fact worth knowing about the file.
"""

from __future__ import annotations

import os
import random
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sto.core.calendar import (
    CalendarCompileError,
    add_working,
    compile_calendar,
    compile_calendars,
)
from sto.core.model.entities import (
    Calendar,
    CalendarException,
    CalendarWeekDay,
    Schedule,
    TimeInterval,
)
from sto.core.model.migrate.sto_v011 import MigrationError, migrate
from sto.legacy import import_mspdi

BOILER_BEFORE = Path(os.environ.get("STO_BOILER_BEFORE", "/home/dez/sto-fixtures/boiler-before-no-progress.xml"))

EIGHT_TO_FOUR = (TimeInterval(8 * 3600, 12 * 3600), TimeInterval(13 * 3600, 17 * 3600))


def _standard(uid=None, **overrides) -> Calendar:
    week = tuple(
        CalendarWeekDay(day=d, working=d in range(2, 7), intervals=EIGHT_TO_FOUR if d in range(2, 7) else ())
        for d in range(1, 8)
    )
    return Calendar(uid=uid or uuid4(), name="Standard", week=week, **overrides)


def _schedule(*calendars: Calendar) -> Schedule:
    return Schedule(schedule_id="cal-test", calendars=tuple(calendars))


MON = datetime(2026, 9, 14)  # a Monday
WEEK = (MON, MON + timedelta(days=7))


class WeeklyPatternTests(unittest.TestCase):
    def test_a_standard_week_compiles_to_ten_intervals(self):
        cal = _standard()
        compiled = compile_calendar(_schedule(cal), cal.uid, WEEK)
        self.assertEqual(len(compiled.intervals.intervals), 10)
        self.assertEqual(compiled.intervals.total_work, 5 * 8 * 3600)
        self.assertEqual(compiled.epoch, MON)

    def test_work_crosses_lunch_and_the_weekend(self):
        cal = _standard()
        compiled = compile_calendar(_schedule(cal), cal.uid, (MON, MON + timedelta(days=14)))
        friday_3pm = compiled.to_seconds(MON + timedelta(days=4, hours=15))
        finish = add_working(compiled.intervals, friday_3pm, 3 * 3600)
        self.assertEqual(compiled.to_datetime(finish), MON + timedelta(days=7, hours=9))

    def test_the_fingerprint_is_stable_and_specific(self):
        cal = _standard()
        a = compile_calendar(_schedule(cal), cal.uid, WEEK)
        b = compile_calendar(_schedule(cal), cal.uid, WEEK)
        self.assertEqual(a.fingerprint, b.fingerprint)
        other = _standard(uid=cal.uid, exceptions=(CalendarException(MON, MON, working=False),))
        self.assertNotEqual(compile_calendar(_schedule(other), cal.uid, WEEK).fingerprint, a.fingerprint)


class InheritanceTests(unittest.TestCase):
    def test_a_derived_calendar_overrides_one_weekday(self):
        base = _standard()
        derived = Calendar(
            uid=uuid4(),
            name="Sat too",
            base_uid=base.uid,
            week=(CalendarWeekDay(day=7, working=True, intervals=(TimeInterval(8 * 3600, 12 * 3600),)),),
        )
        compiled = compile_calendar(_schedule(base, derived), derived.uid, WEEK)
        self.assertEqual(compiled.intervals.total_work, 5 * 8 * 3600 + 4 * 3600)
        self.assertEqual(compiled.lineage, (base.uid, derived.uid))

    def test_a_derived_calendar_inherits_the_base_exception(self):
        base = _standard(exceptions=(CalendarException(MON, MON, working=False, name="holiday"),))
        derived = Calendar(uid=uuid4(), base_uid=base.uid)
        compiled = compile_calendar(_schedule(base, derived), derived.uid, WEEK)
        self.assertEqual(compiled.intervals.total_work, 4 * 8 * 3600)
        self.assertEqual(compiled.exception_days_applied, 1)

    def test_own_exception_overrides_the_inherited_one(self):
        base = _standard(exceptions=(CalendarException(MON, MON, working=False),))
        derived = Calendar(
            uid=uuid4(),
            base_uid=base.uid,
            exceptions=(CalendarException(MON, MON, working=True, intervals=(TimeInterval(0, 86400),)),),
        )
        compiled = compile_calendar(_schedule(base, derived), derived.uid, WEEK)
        self.assertEqual(compiled.intervals.total_work, 4 * 8 * 3600 + 86400)

    def test_a_cycle_is_refused_by_code(self):
        a_uid, b_uid = uuid4(), uuid4()
        a = Calendar(uid=a_uid, base_uid=b_uid)
        b = Calendar(uid=b_uid, base_uid=a_uid)
        with self.assertRaises(CalendarCompileError) as raised:
            compile_calendar(_schedule(a, b), a_uid, WEEK)
        self.assertEqual(raised.exception.code, "CALENDAR_INHERITANCE_CYCLE")

    def test_an_incomplete_top_level_week_is_refused(self):
        cal = Calendar(uid=uuid4(), week=(CalendarWeekDay(day=2, working=True, intervals=EIGHT_TO_FOUR),))
        with self.assertRaises(CalendarCompileError) as raised:
            compile_calendar(_schedule(cal), cal.uid, WEEK)
        self.assertEqual(raised.exception.code, "CALENDAR_WEEK_INCOMPLETE")

    def test_a_missing_base_is_refused(self):
        cal = Calendar(uid=uuid4(), base_uid=uuid4())
        with self.assertRaises(CalendarCompileError) as raised:
            compile_calendar(_schedule(cal), cal.uid, WEEK)
        self.assertEqual(raised.exception.code, "CALENDAR_NOT_FOUND")


class ExceptionTests(unittest.TestCase):
    def test_every_nth_day_for_n_occurrences(self):
        rdo = CalendarException(
            MON, MON + timedelta(days=12), working=False, name="RDO",
            recurrence={"type": "7", "period": "6", "occurrences": "3", "entered_by_occurrences": "1"},
        )
        cal = _standard(exceptions=(rdo,))
        compiled = compile_calendar(_schedule(cal), cal.uid, (MON, MON + timedelta(days=14)))
        # Mon(0) and the following Sun(6) and Sat(12): only the Monday is a working day lost.
        self.assertEqual(compiled.exception_days_applied, 3)
        self.assertEqual(compiled.intervals.total_work, 9 * 8 * 3600)

    def test_occurrences_that_overrun_the_range_are_refused(self):
        bad = CalendarException(
            MON, MON + timedelta(days=5), working=False,
            recurrence={"type": "7", "period": "6", "occurrences": "3", "entered_by_occurrences": "1"},
        )
        cal = _standard(exceptions=(bad,))
        with self.assertRaises(CalendarCompileError) as raised:
            compile_calendar(_schedule(cal), cal.uid, WEEK)
        self.assertEqual(raised.exception.code, "CALENDAR_EXCEPTION_RANGE_INVALID")

    def test_an_unsupported_recurrence_fails_closed(self):
        yearly = CalendarException(MON, MON, working=False, recurrence={"type": "2"})
        cal = _standard(exceptions=(yearly,))
        with self.assertRaises(CalendarCompileError) as raised:
            compile_calendar(_schedule(cal), cal.uid, WEEK)
        self.assertEqual(raised.exception.code, "CALENDAR_EXCEPTION_RECURRENCE_UNSUPPORTED")

    def test_exceptions_outside_the_horizon_are_counted_not_applied(self):
        far = CalendarException(MON + timedelta(days=400), MON + timedelta(days=400), working=False)
        cal = _standard(exceptions=(far,))
        compiled = compile_calendar(_schedule(cal), cal.uid, WEEK)
        self.assertEqual((compiled.exception_days_applied, compiled.exception_days_outside_horizon), (0, 1))

    def test_a_working_exception_with_no_intervals_is_refused(self):
        cal = _standard(exceptions=(CalendarException(MON, MON, working=True),))
        with self.assertRaises(CalendarCompileError) as raised:
            compile_calendar(_schedule(cal), cal.uid, WEEK)
        self.assertEqual(raised.exception.code, "CALENDAR_WORKING_EXCEPTION_EMPTY")

    def test_equal_non_midnight_endpoints_are_refused(self):
        bad = Calendar(
            uid=uuid4(),
            week=tuple(
                CalendarWeekDay(day=d, working=True, intervals=(TimeInterval(3600, 3600),)) for d in range(1, 8)
            ),
        )
        with self.assertRaises(CalendarCompileError) as raised:
            compile_calendar(_schedule(bad), bad.uid, WEEK)
        self.assertEqual(raised.exception.code, "CALENDAR_INTERVAL_INVALID")


class MigrationTests(unittest.TestCase):
    """The gaps recorded against this slice, paid."""

    def _document(self, calendar: dict) -> dict:
        """A real importer document with its calendars replaced."""

        document = import_mspdi(str(Path(__file__).resolve().parent / "fixtures" / "synthetic-basic.mspdi.xml"))
        first = document["calendars"][0]
        calendar = dict(calendar, id=first["id"], external_references=first["external_references"])
        document["calendars"] = [calendar]
        return document

    def _weekdays(self):
        return [
            {"day_type": d, "working": d in range(2, 7),
             "working_times": [{"from": "08:00:00", "to": "17:00:00"}] if d in range(2, 7) else []}
            for d in range(1, 8)
        ]

    def test_a_special_day_becomes_an_exception(self):
        cal = {"id": "calendar:1", "external_references": [{"type": "UID", "value": "1"}],
               "name": "Std", "is_base": True, "base_calendar_ref": None,
               "week_days": self._weekdays() + [{
                   "day_type": 0, "working": False, "working_times": [],
                   "extensions": [{"name": "TimePeriod", "children": [
                       {"name": "FromDate", "text": "2025-04-18T00:00:00"},
                       {"name": "ToDate", "text": "2025-04-18T23:59:00"}]}]}],
               "exceptions": []}
        schedule, _, _ = migrate(self._document(cal))
        calendar = schedule.calendars[0]
        self.assertEqual([d.day for d in calendar.week], list(range(1, 8)))
        self.assertEqual(len(calendar.exceptions), 1)
        self.assertEqual(calendar.exceptions[0].recurrence["source"], "special_day")
        self.assertEqual(calendar.exceptions[0].from_date, datetime(2025, 4, 18))

    def test_recurrence_is_retained_not_flattened(self):
        cal = {"id": "calendar:1", "external_references": [{"type": "UID", "value": "1"}],
               "name": "Std", "is_base": True, "base_calendar_ref": None,
               "week_days": self._weekdays(),
               "exceptions": [{"id": "x", "name": "RDO", "type": 7, "working": False,
                               "entered_by_occurrences": True, "occurrences": 7,
                               "from": "2024-12-18T00:00:00", "to": "2025-01-23T23:59:00",
                               "working_times": [],
                               "raw": {"name": "Exception", "children": [{"name": "Period", "text": "6"}]}}]}
        schedule, _, _ = migrate(self._document(cal))
        rec = schedule.calendars[0].exceptions[0].recurrence
        self.assertEqual(rec, {"source": "exception", "type": "7", "period": "6",
                               "occurrences": "7", "entered_by_occurrences": "1"})

    def test_an_exception_without_dates_fails_closed(self):
        cal = {"id": "calendar:1", "external_references": [{"type": "UID", "value": "1"}],
               "name": "Std", "is_base": True, "base_calendar_ref": None,
               "week_days": self._weekdays(),
               "exceptions": [{"id": "x", "type": 1, "working": False, "from": None, "to": None,
                               "working_times": [], "raw": {}}]}
        with self.assertRaises(MigrationError):
            migrate(self._document(cal))

    def test_a_working_time_missing_a_bound_fails_closed(self):
        days = self._weekdays()
        days[1]["working_times"] = [{"from": "08:00:00", "to": None}]
        cal = {"id": "calendar:1", "external_references": [{"type": "UID", "value": "1"}],
               "name": "Std", "is_base": True, "base_calendar_ref": None,
               "week_days": days, "exceptions": []}
        with self.assertRaises(MigrationError):
            migrate(self._document(cal))


@unittest.skipUnless(BOILER_BEFORE.is_file(), "real BOILER schedule not present")
class BoilerCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = import_mspdi(str(BOILER_BEFORE))
        cls.schedule, _, _ = migrate(cls.document)

    def test_every_calendar_compiles_over_the_schedule_window(self):
        compiled = compile_calendars(self.schedule, (datetime(2026, 8, 17), datetime(2026, 9, 25)))
        self.assertEqual(len(compiled), len(self.schedule.calendars))
        for calendar in compiled.values():
            self.assertTrue(calendar.intervals.intervals, f"{calendar.uid} has no working time")

    def test_every_exception_day_is_outside_the_schedule_window(self):
        """A fact about the file: its calendars came from a 2024-25 template."""

        compiled = compile_calendars(self.schedule, (datetime(2026, 8, 17), datetime(2026, 9, 25)))
        self.assertEqual(sum(c.exception_days_applied for c in compiled.values()), 0)
        self.assertGreater(sum(c.exception_days_outside_horizon for c in compiled.values()), 0)

    def test_a_real_non_working_exception_removes_its_day(self):
        """Compiled over the year the exceptions live in."""

        horizon = (datetime(2024, 12, 1), datetime(2026, 1, 1))
        compiled = compile_calendars(self.schedule, horizon)
        checked = 0
        for calendar in self.schedule.calendars:
            own = compiled[calendar.uid]
            for exception in calendar.exceptions:
                if exception.working or exception.recurrence.get("type") not in ("1", None):
                    continue
                day = exception.from_date.replace(hour=0, minute=0, second=0)
                if not (horizon[0] <= day < horizon[1]):
                    continue
                lo, hi = own.to_seconds(day), own.to_seconds(day + timedelta(days=1))
                self.assertEqual(
                    sum(f - s for s, f in own.intervals.intervals if lo <= s < hi),
                    0,
                    f"{calendar.name}: {exception.name} on {day.date()} still has working time",
                )
                checked += 1
        self.assertGreater(checked, 30)

    def test_the_indexed_arithmetic_agrees_with_the_legacy_engine(self):
        """Ten thousand (moment, duration) pairs across the real calendars.

        The legacy resolver ignores exceptions outside its horizon, which for
        this file is all of them, so the two agree on the weekly pattern alone.
        """

        from sto.legacy.calculation_calendar import _add_working_seconds, _CalendarResolver

        resolver = _CalendarResolver(self.document)
        horizon = (datetime(2026, 8, 1), datetime(2026, 11, 1))
        compiled = compile_calendars(self.schedule, horizon)
        by_external = {c.external_refs[0].uid: c.uid for c in self.schedule.calendars}
        by_ref = {}
        for row in self.document["calendars"]:
            external = next(e["value"] for e in row["external_references"] if e["type"] == "UID")
            by_ref[row["id"]] = (resolver.resolve(row["id"]).pattern, compiled[by_external[external]])
        rng = random.Random(4)
        refs = sorted(by_ref)
        for _ in range(10_000):
            pattern, own = by_ref[rng.choice(refs)]
            moment = datetime(2026, 8, 10) + timedelta(seconds=rng.randint(0, 60 * 86400))
            seconds = rng.randint(0, 5 * 86400)
            expected = _add_working_seconds(moment, seconds, pattern)
            got = add_working(own.intervals, own.to_seconds(moment), seconds)
            self.assertIsNotNone(got, f"{moment} + {seconds}s ran past the horizon")
            self.assertEqual(own.to_datetime(got), expected, f"{moment} + {seconds}s")


if __name__ == "__main__":
    unittest.main()
