"""The backward pass over real schedules: which claims the files actually support.

Three different questions, kept apart on purpose, because running them together
is how an engine comes to look better than it is.

**Does the pass run, and is it self-consistent?** Every activity gets late dates,
every late span consumes exactly the working time its early span did, and two
runs agree. These hold whatever the dates turn out to be.

**Is the float *rule* the one Microsoft Project uses?** Asked against Project's
own stored early and late dates, so the answer does not depend on our forward
pass reproducing them -- and it does not, which is the third question. This is
where the two decisions in :mod:`sto.core.engine.criticality` are settled: that a
float is working time on the activity's calendar rather than a difference of
coordinates, and that a total float is the smaller of the start float and the
finish float. Both are measured here across every real schedule in the estate,
and the counts are pinned so a change to either rule has to be a deliberate one.

**Do our own dates reproduce Project's?** They do not, and this module records
that rather than hiding it. The forward pass agrees with the dates Project
stored on one activity of the un-progressed snapshot, for reasons recorded
undiagnosed in ``docs/history/2026-09-03-forward-pass.md``; a backward pass over
early dates that are wrong produces late dates that are wrong in the same way.
So the late dates are asserted to be *self-consistent*, not correct, and the
count of exact agreements is pinned at what it is so that an improvement shows
up as a failing test rather than going unnoticed.

The real schedules live outside the repository. ``STO_BOILER_BEFORE``,
``STO_KILN`` and ``STO_CALCINER`` name them and ``STO_REQUIRE_BOILER=1`` turns
their absence into a failure instead of a skip, which is what a gate run sets.
"""

from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from sto.core.calendar.arithmetic import working_between
from sto.core.engine import (
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
    span_float,
)
from sto.core.engine.criticality import signed_working
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi

FIXTURES = {
    "boiler_before": Path(
        os.environ.get(
            "STO_BOILER_BEFORE", "/home/dez/sto-fixtures/boiler-before-no-progress.xml"
        )
    ),
    "kiln": Path(os.environ.get("STO_KILN", "/home/dez/sto-fixtures/kiln-wg047k-source.xml")),
    "calciner": Path(
        os.environ.get("STO_CALCINER", "/home/dez/sto-fixtures/calciner-wg050-source.xml")
    ),
}
REQUIRE_BOILER = os.environ.get("STO_REQUIRE_BOILER") == "1"
if REQUIRE_BOILER:
    absent = sorted(name for name, path in FIXTURES.items() if not path.is_file())
    if absent:
        raise RuntimeError(f"STO_REQUIRE_BOILER=1 but these are not here: {absent}")

SKIP_REASON = (
    "the real schedules are not present (they stay outside the repository); "
    "set STO_REQUIRE_BOILER=1 to make this a failure"
)


class _Loaded:
    """One schedule, its plan, both passes and the file's own observations."""

    def __init__(self, path: Path) -> None:
        document = import_mspdi(str(path))
        self.schedule, _, _ = migrate(document)
        start = self.schedule.project.start or datetime(2026, 8, 1)
        self.plan = build_plan(
            self.schedule, (start - timedelta(days=60), start + timedelta(days=365))
        )
        self.network = self.plan.network
        self.forward = forward_pass(self.network, snap_milestones=self.plan.snap_milestones)
        self.backward = backward_pass(
            self.network, self.forward, snap_milestones=self.plan.snap_milestones
        )
        self.floats = float_analysis(
            self.network,
            self.forward,
            self.backward,
            threshold=self.plan.critical_float_threshold,
        )
        # Floats are measured on the task's own or the project's calendar, not
        # the resource's the work is placed on (ADR-010).
        self.calendars = {a.uid: a.float_calendar for a in self.network.activities}
        self.observations = {
            a.uid: a.source_observations
            for a in self.schedule.activities
            if a.source_observations is not None and a.uid in self.calendars
        }

    def stored(self, uid):
        """Project's own early and late coordinates, or ``None`` if incomplete."""

        row = self.observations.get(uid)
        if row is None:
            return None
        if None in (row.early_start, row.early_finish, row.late_start, row.late_finish):
            return None
        return (
            self.plan.to_seconds(row.early_start),
            self.plan.to_seconds(row.early_finish),
            self.plan.to_seconds(row.late_start),
            self.plan.to_seconds(row.late_finish),
        )

    def stored_total_float_agreement(self) -> dict[str, int]:
        """How often each reading reproduces the ``TotalSlack`` in the file.

        Every reading is taken from **Project's own dates**, so this measures the
        rule and nothing else.
        """

        counts = {"working_min": 0, "working_start": 0, "working_finish": 0, "elapsed": 0}
        counts["compared"] = 0
        for uid, calendar in self.calendars.items():
            row = self.observations.get(uid)
            coordinates = self.stored(uid)
            if row is None or coordinates is None or row.total_float_seconds is None:
                continue
            early_start, early_finish, late_start, late_finish = coordinates
            counts["compared"] += 1
            start_float = signed_working(calendar, early_start, late_start)
            finish_float = signed_working(calendar, early_finish, late_finish)
            stored = row.total_float_seconds
            counts["working_start"] += start_float == stored
            counts["working_finish"] += finish_float == stored
            counts["working_min"] += min(start_float, finish_float) == stored
            counts["elapsed"] += span_float(early_finish, late_finish) == stored
        return counts

    def stored_free_float_agreement(self) -> dict[str, int]:
        """Run the production float rule over Project's stored four dates.

        Reimplementing the rule here left this evidence on the pre-C2
        shift-then-measure algorithm after production moved to bounded lag
        inversion. Replacing only the pass coordinates makes the comparison
        call :func:`float_analysis` itself while keeping the file's dates as
        the oracle.
        """

        early = tuple(
            replace(row, early_start=stored[0], early_finish=stored[1])
            for row in self.forward.times
            if (stored := self.stored(row.uid)) is not None
        )
        late = tuple(
            replace(row, late_start=stored[2], late_finish=stored[3])
            for row in self.backward.times
            if (stored := self.stored(row.uid)) is not None
        )
        stored_forward = replace(
            self.forward,
            times=early,
            project_start=min(row.early_start for row in early),
            project_finish=max(row.early_finish for row in early),
        )
        stored_backward = replace(
            self.backward,
            times=late,
            project_late_finish=max(row.late_finish for row in late),
        )
        production = float_analysis(
            self.network,
            stored_forward,
            stored_backward,
            threshold=self.plan.critical_float_threshold,
        )
        compared = [
            row
            for row in production.rows
            if self.observations[row.uid].free_float_seconds is not None
        ]
        return {
            "agreed": sum(
                row.free_float == self.observations[row.uid].free_float_seconds
                for row in compared
            ),
            "compared": len(compared),
        }


@unittest.skipUnless(FIXTURES["boiler_before"].is_file(), SKIP_REASON)
class BackwardPassRunsTests(unittest.TestCase):
    """Properties that hold whatever the dates turn out to be."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.boiler = _Loaded(FIXTURES["boiler_before"])

    def test_every_scheduled_activity_gets_late_dates(self):
        late = self.boiler.backward.by_uid()
        missing = [a.uid for a in self.boiler.network.activities if a.uid not in late]
        self.assertEqual(missing, [], "activities the backward pass did not reach")

    def test_every_late_span_is_ordered(self):
        for row in self.boiler.backward.times:
            self.assertLessEqual(row.late_start, row.late_finish, str(row.uid))

    def test_every_late_span_is_as_long_as_the_early_span_it_mirrors(self):
        early = self.boiler.forward.by_uid()
        # Span length is working time on the calendar the work was *placed*
        # on, which is not the calendar a float is measured in (ADR-010).
        placed_on = {a.uid: a.calendar for a in self.boiler.network.activities}
        for row in self.boiler.backward.times:
            calendar = placed_on[row.uid]
            self.assertEqual(
                working_between(calendar, row.late_start, row.late_finish),
                working_between(
                    calendar,
                    early[row.uid].early_start,
                    early[row.uid].early_finish,
                ),
                f"late span is a different length on {row.uid}",
            )

    def test_the_file_carries_no_constraint_the_backward_pass_would_defer(self):
        """Measured, because it bounds what the difference against Project can be.

        The forward pass already established that this file is entirely ASAP.
        The backward pass has its own list of constraints it declines to answer,
        and this says that list is empty here -- so no difference below is a
        constraint the pass quietly skipped.
        """

        self.assertEqual(self.boiler.backward.deferred_constraints, ())
        self.assertEqual(self.boiler.forward.deferred_constraints, ())

    def test_two_runs_over_one_file_agree(self):
        again = backward_pass(
            self.boiler.network,
            self.boiler.forward,
            snap_milestones=self.boiler.plan.snap_milestones,
        )
        self.assertEqual(self.boiler.backward.fingerprint, again.fingerprint)
        self.assertEqual(
            self.boiler.floats.fingerprint,
            float_analysis(
                self.boiler.network,
                self.boiler.forward,
                again,
                threshold=self.boiler.plan.critical_float_threshold,
            ).fingerprint,
        )

    def test_the_longest_path_has_no_float(self):
        self.assertTrue(
            self.boiler.floats.critical_activities(),
            "no activity has zero float, so nothing drives the finish",
        )

    def test_nothing_has_negative_float_on_a_schedule_with_no_late_constraints(self):
        self.assertEqual(self.boiler.floats.negative_float_activities(), ())


class FloatRuleTests(unittest.TestCase):
    """Which reading of a float the real files support, measured on their own dates.

    These counts are evidence. They are pinned so that changing the float rule
    has to be a decision rather than a side effect, and so an improvement is
    visible as a failing assertion rather than as nothing at all.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.loaded = {
            name: _Loaded(path) for name, path in FIXTURES.items() if path.is_file()
        }
        if not cls.loaded:
            raise unittest.SkipTest("no real schedule fixture is available")

    @unittest.skipUnless(FIXTURES["boiler_before"].is_file(), "BOILER baseline unavailable")
    def test_the_working_time_reading_beats_the_elapsed_one_by_an_order_of_magnitude(self):
        counts = self.loaded["boiler_before"].stored_total_float_agreement()
        self.assertEqual(counts["compared"], 451)
        self.assertEqual(counts["elapsed"], 20)
        self.assertEqual(counts["working_start"], 316)
        self.assertEqual(counts["working_finish"], 361)

    @unittest.skipUnless(FIXTURES["boiler_before"].is_file(), "BOILER baseline unavailable")
    def test_the_smaller_of_the_two_working_floats_is_the_rule_for_boiler(self):
        """Neither component alone reproduces the file; the minimum of them does."""

        self.assertEqual(
            self.loaded["boiler_before"].stored_total_float_agreement()["working_min"], 449
        )

    @unittest.skipUnless(FIXTURES["kiln"].is_file(), "KILN unavailable")
    def test_the_smaller_of_the_two_working_floats_is_the_rule_for_kiln(self):
        kiln = self.loaded["kiln"].stored_total_float_agreement()
        # 416 of 416 since C1: the rule still explains every row it is asked
        # about, and KILN's manually scheduled leaf is no longer one of them.
        self.assertEqual((kiln["working_min"], kiln["compared"]), (416, 416))
    @unittest.skipUnless(FIXTURES["calciner"].is_file(), "CALCINER unavailable")
    def test_the_smaller_of_the_two_working_floats_is_the_rule_for_calciner(self):
        calciner = self.loaded["calciner"].stored_total_float_agreement()
        self.assertEqual((calciner["working_min"], calciner["compared"]), (1763, 1763))

    @unittest.skipUnless(FIXTURES["boiler_before"].is_file(), "BOILER baseline unavailable")
    def test_the_two_rows_the_rule_does_not_explain_are_counted_not_hidden(self):
        counts = self.loaded["boiler_before"].stored_total_float_agreement()
        self.assertEqual(counts["compared"] - counts["working_min"], 2)

    def test_our_free_float_rule_reproduces_the_stored_free_slack(self):
        expected = {
            "boiler_before": (448, 451),
            "kiln": (408, 416),
            "calciner": (1732, 1763),
        }
        for name, loaded in self.loaded.items():
            with self.subTest(name):
                counts = loaded.stored_free_float_agreement()
                self.assertEqual((counts["agreed"], counts["compared"]), expected[name])


class CriticalityRuleTests(unittest.TestCase):
    """``total float <= threshold``, and the threshold the file itself declares."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.loaded = {
            name: _Loaded(path)
            for name, path in FIXTURES.items()
            if name in {"boiler_before", "calciner"} and path.is_file()
        }
        if not cls.loaded:
            raise unittest.SkipTest("no criticality fixture is available")

    @unittest.skipUnless(FIXTURES["boiler_before"].is_file(), "BOILER baseline unavailable")
    def test_the_threshold_rule_reproduces_the_flag_the_file_stored(self):
        """From the file's own slack, so this is the rule and not our dates."""

        boiler = self.loaded["boiler_before"]
        threshold = boiler.plan.critical_float_threshold
        self.assertEqual(threshold, 0)
        rows = [
            row
            for row in boiler.observations.values()
            if row.critical is not None and row.total_float_seconds is not None
        ]
        self.assertEqual(len(rows), 451)
        disagreed = [
            row for row in rows if (row.total_float_seconds <= threshold) != row.critical
        ]
        self.assertEqual(disagreed, [], "the criticality rule is not the file's")

    @unittest.skipUnless(FIXTURES["calciner"].is_file(), "CALCINER unavailable")
    def test_a_declared_critical_slack_limit_is_days_of_the_project_working_day(self):
        """CALCINER is the one file in the estate that sets a non-zero limit.

        It declares six against a 480-minute working day. Reading that as
        working days is what reproduces the file; reading it as calendar days,
        or ignoring it, does not -- and the file's own flags bracket the true
        threshold tightly enough to exclude both.
        """

        calciner = self.loaded["calciner"]
        threshold = calciner.plan.critical_float_threshold
        self.assertEqual(threshold, 172800)
        self.assertEqual(calciner.schedule.project.minutes_per_day, 480)

        rows = [
            row
            for row in calciner.observations.values()
            if row.critical is not None and row.total_float_seconds is not None
        ]
        for name, candidate in (("declared", threshold), ("ignored", 0), ("calendar", 518400)):
            agreed = sum(
                1 for row in rows if (row.total_float_seconds <= candidate) == row.critical
            )
            if name == "declared":
                self.assertEqual(agreed, len(rows), "the declared limit does not reproduce")
            else:
                self.assertLess(agreed, len(rows), f"the {name} reading also reproduces")

        critical = [row.total_float_seconds for row in rows if row.critical]
        ordinary = [row.total_float_seconds for row in rows if not row.critical]
        self.assertLessEqual(max(critical), threshold)
        self.assertGreater(min(ordinary), threshold)


class NotClaimedTests(unittest.TestCase):
    """What the engine does and does not reproduce, pinned so it cannot drift.

    Our late dates inherit whatever the forward pass still gets wrong. Pinning
    the counts at what they are means that moving the forward pass will fail
    these assertions and force the numbers -- and the history entry behind
    them -- to be updated deliberately. They were 0 and 19 until the residue
    was diagnosed (ADR-010) and are the numbers below since.
    """

    @unittest.skipUnless(FIXTURES["boiler_before"].is_file(), "BOILER baseline unavailable")
    def test_our_late_dates_do_not_reproduce_the_ones_project_stored(self):
        boiler = _Loaded(FIXTURES["boiler_before"])
        late = boiler.backward.by_uid()
        exact = 0
        compared = 0
        for uid, row in boiler.observations.items():
            if row.late_start is None or row.late_finish is None:
                continue
            compared += 1
            if (
                boiler.plan.to_datetime(late[uid].late_start) == row.late_start
                and boiler.plan.to_datetime(late[uid].late_finish) == row.late_finish
            ):
                exact += 1
        self.assertEqual(compared, 451)
        self.assertEqual(exact, 409, "the forward pass's remaining difference has moved")

    @unittest.skipUnless(FIXTURES["boiler_before"].is_file(), "BOILER baseline unavailable")
    def test_our_own_float_agrees_with_the_file_on_a_minority_of_rows(self):
        """A local quantity survives a global misplacement better than a date does.

        Free float is the gap between an activity and its immediate successors,
        so it is largely unaffected by the whole schedule sitting in the wrong
        place; total float is measured against the project finish and is not.
        The gap between these two numbers is the shape of the forward pass's
        remaining difference, which is why both are recorded.
        """

        boiler = _Loaded(FIXTURES["boiler_before"])
        ours = boiler.floats.by_uid()
        total = free = compared = 0
        for uid, row in boiler.observations.items():
            if row.total_float_seconds is None or row.free_float_seconds is None:
                continue
            compared += 1
            total += ours[uid].total_float == row.total_float_seconds
            free += ours[uid].free_float == row.free_float_seconds
        self.assertEqual(compared, 451)
        self.assertEqual(total, 380)
        self.assertEqual(free, 435)

    def test_the_other_two_files_are_pinned_at_what_they_are(self):
        """KILN and CALCINER, late dates and floats, so ADR-010's table is a pin.

        KILN's late dates agree on no row because its project finish is set
        by a tail the forward pass still places wrong; CALCINER's agree on
        most. Recorded here rather than only in the ADR so that the numbers
        cannot drift from the code that produces them.
        """

        expected = {
            # KILN's cohort is one row smaller since C1 excluded its manual leaf.
            # KILN's free float rose by one and CALCINER's by six when C2
            # inverted the lag rather than shifting it: both counts are our
            # own float against the file's stored FreeSlack.
            "kiln": (416, 0, 4, 305),
            # Four SS predecessors previously counted the exclusive end of a
            # working interval as a movable start. C2 now pulls that inverse
            # back to the latest valid start coordinate, so those four
            # one-second boundary overstatements no longer match the stored
            # whole-unit free slack.
            "calciner": (1763, 1572, 1488, 1691),
        }
        available = {
            name: values for name, values in expected.items() if FIXTURES[name].is_file()
        }
        if not available:
            self.skipTest("KILN and CALCINER are unavailable")
        for name, (compared_expected, late_expected, total_expected, free_expected) in available.items():
            with self.subTest(name):
                loaded = _Loaded(FIXTURES[name])
                late = loaded.backward.by_uid()
                ours = loaded.floats.by_uid()
                compared = late_exact = total = free = 0
                for uid, row in loaded.observations.items():
                    if None in (
                        row.late_start,
                        row.late_finish,
                        row.total_float_seconds,
                        row.free_float_seconds,
                    ):
                        continue
                    compared += 1
                    late_exact += (
                        loaded.plan.to_datetime(late[uid].late_start) == row.late_start
                        and loaded.plan.to_datetime(late[uid].late_finish) == row.late_finish
                    )
                    total += ours[uid].total_float == row.total_float_seconds
                    free += ours[uid].free_float == row.free_float_seconds
                self.assertEqual(
                    (compared, late_exact, total, free),
                    (compared_expected, late_expected, total_expected, free_expected),
                )


if __name__ == "__main__":
    unittest.main()
