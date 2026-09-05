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
from sto.core.engine.network import shift_lag
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

PRESENT = all(path.is_file() for path in FIXTURES.values())
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
        """How often our free-float rule reproduces the ``FreeSlack`` in the file."""

        outgoing = self.network.successors()
        early = {}
        for uid in self.calendars:
            coordinates = self.stored(uid)
            if coordinates is not None:
                early[uid] = (coordinates[0], coordinates[1])
        project_finish = max((finish for _, finish in early.values()), default=0)

        counts = {"agreed": 0, "compared": 0}
        for uid, calendar in self.calendars.items():
            row = self.observations.get(uid)
            if row is None or row.free_float_seconds is None or uid not in early:
                continue
            edges = [r for r in outgoing[uid] if r.successor_uid in early]
            counts["compared"] += 1
            if not edges:
                ours = signed_working(calendar, early[uid][1], project_finish)
            else:
                slacks = []
                for relationship in edges:
                    anchor = (
                        early[uid][1]
                        if relationship.anchors_predecessor_finish
                        else early[uid][0]
                    )
                    lag_calendar = (
                        relationship.lag_calendar
                        if relationship.lag_calendar is not None
                        else self.calendars[relationship.successor_uid]
                    )
                    required = shift_lag(lag_calendar, anchor, relationship.lag)
                    successor = early[relationship.successor_uid]
                    available = (
                        successor[0] if relationship.bounds_successor_start else successor[1]
                    )
                    slacks.append(signed_working(calendar, required, available))
                ours = min(slacks)
            counts["agreed"] += ours == row.free_float_seconds
        return counts


@unittest.skipUnless(PRESENT, SKIP_REASON)
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


@unittest.skipUnless(PRESENT, SKIP_REASON)
class FloatRuleTests(unittest.TestCase):
    """Which reading of a float the real files support, measured on their own dates.

    These counts are evidence. They are pinned so that changing the float rule
    has to be a decision rather than a side effect, and so an improvement is
    visible as a failing assertion rather than as nothing at all.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.boiler = _Loaded(FIXTURES["boiler_before"])
        cls.kiln = _Loaded(FIXTURES["kiln"])
        cls.calciner = _Loaded(FIXTURES["calciner"])

    def test_the_working_time_reading_beats_the_elapsed_one_by_an_order_of_magnitude(self):
        counts = self.boiler.stored_total_float_agreement()
        self.assertEqual(counts["compared"], 451)
        self.assertEqual(counts["elapsed"], 20)
        self.assertEqual(counts["working_start"], 316)
        self.assertEqual(counts["working_finish"], 361)

    def test_the_smaller_of_the_two_working_floats_is_the_rule_project_uses(self):
        """Neither component alone reproduces the file; the minimum of them does."""

        self.assertEqual(self.boiler.stored_total_float_agreement()["working_min"], 449)
        kiln = self.kiln.stored_total_float_agreement()
        self.assertEqual((kiln["working_min"], kiln["compared"]), (417, 417))
        calciner = self.calciner.stored_total_float_agreement()
        self.assertEqual((calciner["working_min"], calciner["compared"]), (1763, 1763))

    def test_the_two_rows_the_rule_does_not_explain_are_counted_not_hidden(self):
        counts = self.boiler.stored_total_float_agreement()
        self.assertEqual(counts["compared"] - counts["working_min"], 2)

    def test_our_free_float_rule_reproduces_the_stored_free_slack(self):
        boiler = self.boiler.stored_free_float_agreement()
        self.assertEqual((boiler["agreed"], boiler["compared"]), (448, 451))
        kiln = self.kiln.stored_free_float_agreement()
        self.assertEqual((kiln["agreed"], kiln["compared"]), (407, 417))
        calciner = self.calciner.stored_free_float_agreement()
        self.assertEqual((calciner["agreed"], calciner["compared"]), (1730, 1763))


@unittest.skipUnless(PRESENT, SKIP_REASON)
class CriticalityRuleTests(unittest.TestCase):
    """``total float <= threshold``, and the threshold the file itself declares."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.boiler = _Loaded(FIXTURES["boiler_before"])
        cls.calciner = _Loaded(FIXTURES["calciner"])

    def test_the_threshold_rule_reproduces_the_flag_the_file_stored(self):
        """From the file's own slack, so this is the rule and not our dates."""

        threshold = self.boiler.plan.critical_float_threshold
        self.assertEqual(threshold, 0)
        rows = [
            row
            for row in self.boiler.observations.values()
            if row.critical is not None and row.total_float_seconds is not None
        ]
        self.assertEqual(len(rows), 451)
        disagreed = [
            row for row in rows if (row.total_float_seconds <= threshold) != row.critical
        ]
        self.assertEqual(disagreed, [], "the criticality rule is not the file's")

    def test_a_declared_critical_slack_limit_is_days_of_the_project_working_day(self):
        """CALCINER is the one file in the estate that sets a non-zero limit.

        It declares six against a 480-minute working day. Reading that as
        working days is what reproduces the file; reading it as calendar days,
        or ignoring it, does not -- and the file's own flags bracket the true
        threshold tightly enough to exclude both.
        """

        threshold = self.calciner.plan.critical_float_threshold
        self.assertEqual(threshold, 172800)
        self.assertEqual(self.calciner.schedule.project.minutes_per_day, 480)

        rows = [
            row
            for row in self.calciner.observations.values()
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


@unittest.skipUnless(PRESENT, SKIP_REASON)
class NotClaimedTests(unittest.TestCase):
    """What the engine does and does not reproduce, pinned so it cannot drift.

    Our late dates inherit whatever the forward pass still gets wrong. Pinning
    the counts at what they are means that moving the forward pass will fail
    these assertions and force the numbers -- and the history entry behind
    them -- to be updated deliberately. They were 0 and 19 until the residue
    was diagnosed (ADR-010) and are the numbers below since.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.boiler = _Loaded(FIXTURES["boiler_before"])

    def test_our_late_dates_do_not_reproduce_the_ones_project_stored(self):
        late = self.boiler.backward.by_uid()
        exact = 0
        compared = 0
        for uid, row in self.boiler.observations.items():
            if row.late_start is None or row.late_finish is None:
                continue
            compared += 1
            if (
                self.boiler.plan.to_datetime(late[uid].late_start) == row.late_start
                and self.boiler.plan.to_datetime(late[uid].late_finish) == row.late_finish
            ):
                exact += 1
        self.assertEqual(compared, 451)
        self.assertEqual(exact, 409, "the forward pass's remaining difference has moved")

    def test_our_own_float_agrees_with_the_file_on_a_minority_of_rows(self):
        """A local quantity survives a global misplacement better than a date does.

        Free float is the gap between an activity and its immediate successors,
        so it is largely unaffected by the whole schedule sitting in the wrong
        place; total float is measured against the project finish and is not.
        The gap between these two numbers is the shape of the forward pass's
        remaining difference, which is why both are recorded.
        """

        ours = self.boiler.floats.by_uid()
        total = free = compared = 0
        for uid, row in self.boiler.observations.items():
            if row.total_float_seconds is None or row.free_float_seconds is None:
                continue
            compared += 1
            total += ours[uid].total_float == row.total_float_seconds
            free += ours[uid].free_float == row.free_float_seconds
        self.assertEqual(compared, 451)
        self.assertEqual(total, 380)
        self.assertEqual(free, 435)


if __name__ == "__main__":
    unittest.main()
