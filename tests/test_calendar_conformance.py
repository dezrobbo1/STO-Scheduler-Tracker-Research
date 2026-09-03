"""The calendar cases of the semantic corpus, on the compiled arithmetic alone.

The corpus lives in ``dezrobbo1/PM-Software`` at the commit pinned in
``docs/history/``; until the conformance suite arrives (S3, when the corpus is
copied in with SHA-256 pins) these cases are read from a clone named by
``STO_PM_SOFTWARE_DIR``. ``STO_REQUIRE_PM=1`` turns its absence into a failure.

Only the cases a calendar can answer by itself are here: one activity, or
one activity and a resource calendar. The cases with relationships are the
forward pass's, and are left for it.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from sto.core.calendar.arithmetic import (
    CompiledIntervals,
    add_working,
    intersect_intervals,
    next_working,
)

PM_DIR = Path(os.environ.get("STO_PM_SOFTWARE_DIR", "/home/dez/PM-Software"))
CASES = PM_DIR / "benchmarks" / "semantic" / "cases"
REQUIRE = os.environ.get("STO_REQUIRE_PM") == "1"
if REQUIRE and not CASES.is_dir():
    raise RuntimeError(f"STO_REQUIRE_PM=1 but {CASES} is not there")

CALENDAR_ONLY = ("sem-cal-021", "sem-cal-022", "sem-cal-023", "sem-cal-026", "sem-cal-027", "sem-cal-028")


@unittest.skipUnless(CASES.is_dir(), "PM-Software clone not present; set STO_REQUIRE_PM=1 to fail")
class CalendarCaseTests(unittest.TestCase):
    def _run(self, case_id: str):
        case = json.loads((CASES / f"{case_id}.json").read_text(encoding="utf-8"))
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
