"""The calendar cases of the semantic corpus, on the compiled arithmetic alone.

The cases are the pinned copy in :mod:`sto.conformance`, hash-checked as they
are read; :mod:`tests.test_conformance_corpus` guards the pins.

Only the cases a calendar can answer by itself are here: one activity, or
one activity and a resource calendar. The cases with relationships are the
forward pass's, and are left for it.
"""

from __future__ import annotations

import unittest

from sto import conformance
from sto.core.calendar.arithmetic import (
    CompiledIntervals,
    add_working,
    intersect_intervals,
    next_working,
)

CALENDAR_ONLY = ("sem-cal-021", "sem-cal-022", "sem-cal-023", "sem-cal-026", "sem-cal-027", "sem-cal-028")


class CalendarCaseTests(unittest.TestCase):
    def _run(self, case_id: str):
        case = conformance.load_case(case_id)
        schedule = case["schedule"]
        calendars = {c["id"]: tuple(tuple(i) for i in c["working_intervals"]) for c in schedule["calendars"]}
        resources = {r["id"]: r for r in schedule.get("resources", [])}
        project_start = schedule["project"]["project_start"]
        self.assertFalse(schedule["relationships"], "not a calendar-only case")
        got = {}
        for activity in schedule["activities"]:
            intervals = calendars[activity["calendar_id"]]
            for assignment in activity.get("assignments", []):
                resource = resources[assignment["resource_id"]]
                if resource.get("calendar_id"):
                    intervals = intersect_intervals(intervals, calendars[resource["calendar_id"]])
            compiled = CompiledIntervals.of(intervals)
            floor = project_start
            for constraint in activity.get("constraints", []):
                if constraint["type"] != "start_no_earlier_than":
                    self.fail(f"{case_id}: constraint {constraint['type']} is not a calendar question")
                floor = max(floor, constraint["value"])
            start = next_working(compiled, floor)
            finish = add_working(compiled, start, activity["duration"])
            got[activity["id"]] = {"start": start, "finish": finish}
        self.assertEqual(got, case["expected"]["activity_times"], case["title"])
        self.assertEqual(max(v["finish"] for v in got.values()), case["expected"]["project_finish"])

    def test_sem_cal_021_duration_spans_lunch(self):
        self._run("sem-cal-021")

    def test_sem_cal_022_duration_spans_overnight(self):
        self._run("sem-cal-022")

    def test_sem_cal_023_duration_spans_weekend(self):
        self._run("sem-cal-023")

    def test_sem_cal_026_activity_calendars_differ(self):
        self._run("sem-cal-026")

    def test_sem_cal_027_resource_calendar_delays_work(self):
        self._run("sem-cal-027")

    def test_sem_cal_028_holiday_exception(self):
        self._run("sem-cal-028")


if __name__ == "__main__":
    unittest.main()
