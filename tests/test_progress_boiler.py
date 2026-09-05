"""The status date and progress over the real schedules: what they actually support.

Four questions, kept apart, because the four files answer different ones and
running them together is how a weak oracle borrows a strong one's authority.

**Does the pass reproduce the dates Project stored for work that has happened?**
Yes. For completed work trivially so: an actual date is a fact and the pass
places it unchanged. For the one activity under way it is not trivial at all:
its status date is sixteen months stale and it started five weeks before its
own project start, so where its remaining eight hours go is a rule, and the
rule the file shows is *from the actual start, on the task calendar* --
finishing on the following Monday, exactly where Project put it. Both are
asserted, because this is the one part of the engine that *should* agree
exactly with the file, and a regression that stopped it agreeing would
otherwise be invisible next to the forward pass's known disagreement about
everything else. Until this assertion covered the forecast finish, the row was
placed three weeks late and nothing said so.

**Is a completed activity critical?** No, and this is where the estate's files
disagree with each other in a way that matters. The two files Microsoft Project
itself recalculated after progress was entered store, for every completed
activity, a late start and late finish equal to the actual dates, a total slack
of zero, and ``Critical`` false. The threshold rule from S4 -- total float at or
below the project's threshold -- would call all of them critical. So criticality
needs the second half it did not have, and the backward pass needs to pin
completed work. Both are asserted here against the files that were genuinely
recalculated, never against the candidate.

**Is the day-5 candidate an oracle for late dates?** It is not, and that is
asserted rather than assumed, because it is the file the roadmap calls the only
progress oracle and it would be easy to read its slack as evidence. Its
completed rows carry early dates equal to their actuals -- so it *is* an oracle
for those -- and late dates three weeks later with a positive stored slack,
which is what a file written by tooling rather than recalculated by Project
looks like.

**Can these files prove the status-date rule?** No. Every BOILER variant in the
estate declares ``StatusDate`` 2025-05-09, sixteen months *before* its own
project start, exactly as their calendars came from a 2024-25 template. The
status date therefore falls outside the compiled window on every one of them and
the plan reports it rather than using it, so the rule that remaining work is
scheduled from the status date is proven by the conformance corpus and by no
file here. That is asserted below so that a file which one day carries a usable
status date makes this test fail and asks for the claim to be widened.

The real schedules live outside the repository. ``STO_BOILER_DAY5``,
``STO_BOILER_AFTER_NATIVE`` and ``STO_BOILER_ROUNDTRIP_SAVED`` name them and
``STO_REQUIRE_BOILER=1`` turns their absence into a failure instead of a skip,
which is what a gate run sets.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sto.core.engine import (
    ProgressState,
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
)
from sto.core.engine.progress import state_of
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi

FIXTURES = {
    "day5": Path(
        os.environ.get(
            "STO_BOILER_DAY5",
            "/home/dez/sto-fixtures/BOILER-WG110-day5-candidate.mspdi.xml",
        )
    ),
    "after_native": Path(
        os.environ.get(
            "STO_BOILER_AFTER_NATIVE",
            "/home/dez/sto-fixtures/boiler-after-native-progress.xml",
        )
    ),
    "roundtrip_saved": Path(
        os.environ.get(
            "STO_BOILER_ROUNDTRIP_SAVED",
            "/home/dez/sto-fixtures/boiler-roundtrip-project-saved-task43.xml",
        )
    ),
}

#: The files Microsoft Project itself recalculated after progress was entered.
#: The candidate is deliberately not one of them.
NATIVELY_RECALCULATED = ("after_native", "roundtrip_saved")

REQUIRE_BOILER = os.environ.get("STO_REQUIRE_BOILER") == "1"
if REQUIRE_BOILER:
    for _name, _path in FIXTURES.items():
        if not _path.is_file():
            raise RuntimeError(
                f"STO_REQUIRE_BOILER=1 but the real schedule is not here: {_path}"
            )

_PRESENT = all(path.is_file() for path in FIXTURES.values())
_LOADED: dict[str, tuple] = {}


def _load(name: str):
    """The schedule, its plan and the three passes, computed once per file."""

    if name not in _LOADED:
        schedule, _, _ = migrate(import_mspdi(str(FIXTURES[name])))
        start = schedule.project.start or datetime(2026, 8, 1)
        horizon = (start - timedelta(days=90), start + timedelta(days=365))
        plan = build_plan(schedule, horizon)
        forward = forward_pass(
            plan.network,
            snap_milestones=plan.snap_milestones,
            progress_policy=plan.progress_policy,
        )
        backward = backward_pass(
            plan.network,
            forward,
            snap_milestones=plan.snap_milestones,
            progress_policy=plan.progress_policy,
        )
        floats = float_analysis(
            plan.network,
            forward,
            backward,
            threshold=plan.critical_float_threshold,
        )
        _LOADED[name] = (schedule, plan, forward, backward, floats)
    return _LOADED[name]


def _completed(schedule):
    """The activities the file reports finished, with the values Project stored."""

    return [
        activity
        for activity in schedule.activities
        if activity.actual_finish is not None
        and activity.source_observations is not None
    ]


@unittest.skipUnless(
    _PRESENT,
    "the real BOILER schedules are not present (they stay outside the repository); "
    "set STO_REQUIRE_BOILER=1 to make this a failure",
)
class ReportedWorkTests(unittest.TestCase):
    """Work that has happened is placed where the file says it happened."""

    def test_every_activity_with_an_actual_date_keeps_the_dates_project_stored(self):
        for name in FIXTURES:
            with self.subTest(name):
                schedule, plan, forward, _, _ = _load(name)
                times = forward.by_uid()
                checked = 0
                for activity in schedule.activities:
                    row = times.get(activity.uid)
                    observations = activity.source_observations
                    if row is None or observations is None:
                        continue
                    if activity.actual_start is None:
                        continue
                    checked += 1
                    self.assertEqual(
                        plan.to_datetime(row.early_start),
                        observations.start,
                        f"{name}: {activity.code or activity.name} start",
                    )
                    # The finish too -- an actual finish for completed work,
                    # and for work under way the forecast finish Project
                    # itself computed from the actual start and what is left.
                    self.assertEqual(
                        plan.to_datetime(row.early_finish),
                        observations.finish,
                        f"{name}: {activity.code or activity.name} finish",
                    )
                self.assertGreater(checked, 0, f"{name} carries no reported work")

    def test_the_in_progress_row_is_placed_from_its_actual_start_not_the_project_start(self):
        """The rule the one in-progress row in the estate settles.

        Its actual start is weeks before the project start, and Project's own
        forecast finish is the remaining duration consumed from the actual
        start on the task calendar. A pass that floored started work at the
        project start put this row three weeks late; the row is pinned here so
        that it cannot again.
        """

        schedule, plan, forward, _, _ = _load("day5")
        rows = [row for row in forward.times if row.state is ProgressState.IN_PROGRESS]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        activity = next(a for a in schedule.activities if a.uid == row.uid)
        self.assertLess(activity.actual_start, schedule.project.start)
        self.assertEqual(plan.to_datetime(row.remaining_start), activity.actual_start)
        self.assertEqual(
            plan.to_datetime(row.early_finish), activity.source_observations.finish
        )
        # The floor is the actual start and not the end of work already done:
        # this row reports none done, so the two coincide and the second is
        # not measured. A row with an actual duration would tell them apart.
        self.assertEqual(activity.actual_duration.seconds, 0)
        self.assertIsNone(activity.resume)

    def test_the_day_five_candidate_carries_the_progress_the_register_records(self):
        schedule, plan, forward, _, _ = _load("day5")
        states = forward.by_state()
        self.assertEqual(len(states[ProgressState.COMPLETE]), 7)
        self.assertEqual(len(states[ProgressState.IN_PROGRESS]), 1)
        # Eight tasks with actuals, as `fixtures/README.md` records for this file.
        self.assertEqual(
            len([a for a in schedule.activities if a.actual_start is not None]), 8
        )

    def test_the_dates_and_the_percentages_agree_on_every_row(self):
        """The engine reads the dates; this is why nothing is lost by that.

        A percentage says how much is done, not when it happened, and the
        conformance corpus carries none at all -- so the pass reads dates. On
        both real files the two agree exactly, and that agreement is asserted
        rather than assumed: a file where they diverge should fail here and be
        decided deliberately, not resolved by whichever the code happened to
        read.
        """

        for name in ("day5", "after_native"):
            with self.subTest(name):
                schedule, _, forward, _, _ = _load(name)
                for activity in schedule.activities:
                    percent = activity.percent_complete.duration_permille
                    self.assertEqual(
                        percent > 0,
                        activity.actual_start is not None,
                        f"{name}: {activity.code or activity.name} started",
                    )
                    self.assertEqual(
                        percent >= 1000,
                        activity.actual_finish is not None,
                        f"{name}: {activity.code or activity.name} finished",
                    )
                self.assertGreater(len(forward.complete_activities()), 0)


@unittest.skipUnless(
    _PRESENT,
    "the real BOILER schedules are not present; set STO_REQUIRE_BOILER=1",
)
class NativeRecalculationTests(unittest.TestCase):
    """What Project itself did to completed work, and what that settles."""

    def test_project_pins_completed_work_in_both_directions(self):
        for name in NATIVELY_RECALCULATED:
            with self.subTest(name):
                schedule, _, _, _, _ = _load(name)
                completed = _completed(schedule)
                self.assertGreater(len(completed), 0)
                for activity in completed:
                    observations = activity.source_observations
                    self.assertEqual(observations.late_start, activity.actual_start)
                    self.assertEqual(observations.late_finish, activity.actual_finish)
                    self.assertEqual(observations.early_start, activity.actual_start)
                    self.assertEqual(observations.early_finish, activity.actual_finish)
                    self.assertEqual(observations.total_float_seconds, 0)

    def test_the_threshold_rule_alone_would_call_every_one_of_them_critical(self):
        """The S4 rule's failure, counted rather than described.

        Zero stored slack is at the project's threshold, so total-float-alone
        says critical; the file says false. That gap is the whole reason
        criticality has a second half.
        """

        wrong = 0
        for name in NATIVELY_RECALCULATED:
            schedule, plan, _, _, _ = _load(name)
            for activity in _completed(schedule):
                observations = activity.source_observations
                threshold_says_critical = (
                    observations.total_float_seconds <= plan.critical_float_threshold
                )
                self.assertTrue(threshold_says_critical)
                self.assertFalse(observations.critical)
                wrong += 1
        self.assertEqual(wrong, 4)

    def test_our_criticality_agrees_with_the_file_on_completed_work(self):
        for name in NATIVELY_RECALCULATED:
            with self.subTest(name):
                schedule, _, _, _, floats = _load(name)
                rows = floats.by_uid()
                for activity in _completed(schedule):
                    row = rows[activity.uid]
                    self.assertTrue(row.complete)
                    self.assertFalse(row.critical, activity.code or activity.name)
                    self.assertEqual(row.total_float, 0)

    def test_our_late_dates_for_completed_work_are_its_actual_dates(self):
        for name in NATIVELY_RECALCULATED:
            with self.subTest(name):
                schedule, plan, _, backward, _ = _load(name)
                late = backward.by_uid()
                for activity in _completed(schedule):
                    row = late[activity.uid]
                    self.assertEqual(
                        plan.to_datetime(row.late_start), activity.actual_start
                    )
                    self.assertEqual(
                        plan.to_datetime(row.late_finish), activity.actual_finish
                    )


@unittest.skipUnless(
    _PRESENT,
    "the real BOILER schedules are not present; set STO_REQUIRE_BOILER=1",
)
class CandidateIsNotALateDateOracleTests(unittest.TestCase):
    """The day-5 candidate's slack was never recalculated, and says so."""

    def test_its_completed_rows_keep_late_dates_the_actuals_have_left_behind(self):
        schedule, _, _, _, _ = _load("day5")
        completed = _completed(schedule)
        self.assertEqual(len(completed), 7)
        for activity in completed:
            observations = activity.source_observations
            # Early dates are the actuals: an oracle for those.
            self.assertEqual(observations.early_start, activity.actual_start)
            self.assertEqual(observations.early_finish, activity.actual_finish)
            # Late dates are not, and the slack is positive rather than zero.
            self.assertNotEqual(observations.late_start, activity.actual_start)
            self.assertGreater(observations.total_float_seconds, 0)

    def test_which_is_why_the_completion_rule_is_not_measured_against_it(self):
        # Every completed row here is already non-critical on slack alone, so
        # the file cannot distinguish the two rules. Asserted so that it is
        # never quoted as evidence for the one it does not test.
        schedule, plan, _, _, _ = _load("day5")
        for activity in _completed(schedule):
            observations = activity.source_observations
            self.assertGreater(
                observations.total_float_seconds, plan.critical_float_threshold
            )
            self.assertFalse(observations.critical)


@unittest.skipUnless(
    _PRESENT,
    "the real BOILER schedules are not present; set STO_REQUIRE_BOILER=1",
)
class StatusDateIsNotMeasurableHereTests(unittest.TestCase):
    """No file in the estate carries a status date inside its own schedule."""

    def test_every_file_declares_a_status_date_before_its_own_project_start(self):
        for name in FIXTURES:
            with self.subTest(name):
                schedule, _, _, _, _ = _load(name)
                project = schedule.project
                self.assertIsNotNone(project.status_date)
                self.assertIsNotNone(project.start)
                self.assertLess(project.status_date, project.start)

    def test_so_the_plan_reports_the_status_date_rather_than_using_it(self):
        for name in FIXTURES:
            with self.subTest(name):
                _, plan, _, _, _ = _load(name)
                self.assertTrue(plan.status_time_outside_window)
                self.assertIsNone(plan.network.status_time)

    def test_and_no_activity_is_held_at_a_status_date_it_does_not_have(self):
        from sto.core.engine import FROM_STATUS_TIME

        for name in FIXTURES:
            with self.subTest(name):
                _, _, forward, _, _ = _load(name)
                self.assertEqual(
                    [row.uid for row in forward.times if row.source == FROM_STATUS_TIME],
                    [],
                )


if __name__ == "__main__":
    unittest.main()
