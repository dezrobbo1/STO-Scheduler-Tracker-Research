"""Every leaf is answered exactly once (slice S6).

The first half of `P1-G2` asks that every leaf activity of the BOILER
snapshots gets a disposition. That is a partition claim, and a partition has
two halves: nothing falls between the sets, and nothing lands in both. A row
that is scheduled *and* excluded, or excluded twice under different codes,
would make a count of "dispositioned rows" agree with the leaf count while the
answer underneath it was incoherent.

So this asks the question directly, of every real schedule here rather than
of BOILER alone, and of the assumption channel too: an assumption is a
statement about a row the plan scheduled, so one naming an excluded row is a
claim about a calculation that did not happen.

The real schedules live outside the repository; ``STO_REQUIRE_BOILER=1`` turns
their absence into a failure instead of a skip.
"""

from __future__ import annotations

import os
import unittest
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from calculation_fixture import _activity, _document

from sto.core.engine import build_plan
from sto.core.model.entities import Constraint
from sto.core.model.enums import ConstraintType
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi

FIXTURES = {
    "boiler_before": Path(
        os.environ.get("STO_BOILER_BEFORE", "/home/dez/sto-fixtures/boiler-before-no-progress.xml")
    ),
    "kiln": Path(os.environ.get("STO_KILN", "/home/dez/sto-fixtures/kiln-wg047k-source.xml")),
    "calciner": Path(
        os.environ.get("STO_CALCINER", "/home/dez/sto-fixtures/calciner-wg050-source.xml")
    ),
    "day5": Path(
        os.environ.get(
            "STO_BOILER_DAY5", "/home/dez/sto-fixtures/BOILER-WG110-day5-candidate.mspdi.xml"
        )
    ),
}
if os.environ.get("STO_REQUIRE_BOILER") == "1":
    absent = sorted(name for name, path in FIXTURES.items() if not path.is_file())
    if absent:
        raise RuntimeError(f"STO_REQUIRE_BOILER=1 but these are not here: {absent}")
ALL_PRESENT = all(path.is_file() for path in FIXTURES.values())


def _planned(path: Path):
    schedule, _, _ = migrate(import_mspdi(str(path)))
    start = schedule.project.start or datetime(2026, 8, 1)
    return schedule, build_plan(
        schedule, (start - timedelta(days=90), start + timedelta(days=365))
    )


@unittest.skipUnless(
    ALL_PRESENT,
    "the real schedules are not present (they stay outside the repository); "
    "set STO_REQUIRE_BOILER=1 to make this a failure",
)
class DispositionPartitionTests(unittest.TestCase):
    def test_every_activity_is_scheduled_or_excluded(self):
        for name, path in FIXTURES.items():
            with self.subTest(name):
                schedule, plan = _planned(path)
                scheduled = {row.uid for row in plan.network.activities}
                excluded = {row.uid for row in plan.excluded if row.kind == "activity"}
                undecided = [
                    activity.uid
                    for activity in schedule.activities
                    if activity.uid not in scheduled and activity.uid not in excluded
                ]
                self.assertEqual(undecided, [], "activities with no disposition at all")

    def test_and_never_both(self):
        for name, path in FIXTURES.items():
            with self.subTest(name):
                _, plan = _planned(path)
                scheduled = {row.uid for row in plan.network.activities}
                excluded = {row.uid for row in plan.excluded if row.kind == "activity"}
                self.assertEqual(sorted(scheduled & excluded, key=str), [])

    def test_and_never_excluded_twice(self):
        """Two codes for one row would make the reason for it ambiguous."""

        for name, path in FIXTURES.items():
            with self.subTest(name):
                _, plan = _planned(path)
                counted = Counter(row.uid for row in plan.excluded if row.kind == "activity")
                self.assertEqual([uid for uid, n in counted.items() if n > 1], [])

    def test_an_assumption_names_a_row_the_plan_scheduled(self):
        for name, path in FIXTURES.items():
            with self.subTest(name):
                _, plan = _planned(path)
                scheduled = {row.uid for row in plan.network.activities}
                stray = [
                    row.uid
                    for row in plan.assumed
                    if row.kind == "activity" and row.uid not in scheduled
                ]
                self.assertEqual(stray, [], "an assumption about a calculation that did not happen")

    def test_every_relationship_is_planned_or_excluded(self):
        """The same partition, asked of the edges."""

        for name, path in FIXTURES.items():
            with self.subTest(name):
                schedule, plan = _planned(path)
                planned = {row.uid for row in plan.network.relationships}
                excluded = {row.uid for row in plan.excluded if row.kind == "relationship"}
                undecided = [
                    relationship.uid
                    for relationship in schedule.relationships
                    if relationship.uid not in planned and relationship.uid not in excluded
                ]
                self.assertEqual(undecided, [], "relationships with no disposition at all")
                self.assertEqual(sorted(planned & excluded, key=str), [])



class ThePartitionHoldsWithoutTheRealFilesTests(unittest.TestCase):
    """The same invariant, on shapes the corpus of real files does not carry.

    The real schedules are the evidence that this holds where it matters, and
    they are absent from an ordinary CI run. That left the property provable
    only on four files that happen not to exercise every canonical field: a
    secondary constraint, for one, which no file here carries and which the
    planner reported as an *exclusion* on a row it went on to schedule. So
    these run everywhere, from documents built in the test.
    """

    def _plan(self, schedule):
        start = schedule.project.start or datetime(2026, 1, 5)
        return build_plan(schedule, (start - timedelta(days=90), start + timedelta(days=365)))

    def _task(self, uid):
        return _activity(
            uid,
            start="2026-01-05T09:00:00",
            finish="2026-01-05T10:00:00",
            duration_seconds=3600,
        )

    def _partition(self, plan, schedule):
        scheduled = {row.uid for row in plan.network.activities}
        excluded = Counter(row.uid for row in plan.excluded if row.kind == "activity")
        self.assertEqual(
            sorted(scheduled & set(excluded), key=str), [], "scheduled and excluded"
        )
        self.assertEqual(
            [uid for uid, count in excluded.items() if count > 1], [], "excluded twice"
        )
        undecided = [
            activity.uid
            for activity in schedule.activities
            if activity.uid not in scheduled and activity.uid not in excluded
        ]
        self.assertEqual(undecided, [], "no disposition at all")
        stray = [
            row.uid
            for row in plan.assumed
            if row.kind == "activity" and row.uid not in scheduled
        ]
        self.assertEqual(stray, [], "an assumption about a calculation that did not happen")

    def test_an_ordinary_pair_partitions(self):
        schedule, _, _ = migrate(_document([self._task(1), self._task(2)]))
        self._partition(self._plan(schedule), schedule)

    def test_a_secondary_constraint_does_not_answer_its_row_twice(self):
        """The shape no real file here carries, and the one that was wrong.

        A second constraint is not applied, and that is worth recording -- but
        the row is scheduled, so the record is an assumption about a placed
        activity, not a disposition. As an exclusion it made one activity both.
        """

        schedule, _, _ = migrate(_document([self._task(1), self._task(2)]))
        first = schedule.activities[0]
        constrained = replace(
            first,
            secondary_constraint=Constraint(
                type=ConstraintType.FNLT, date=datetime(2026, 1, 9, 16)
            ),
        )
        schedule = replace(schedule, activities=(constrained,) + schedule.activities[1:])
        plan = self._plan(schedule)

        self._partition(plan, schedule)
        self.assertIn(
            "ACTIVITY_SECONDARY_CONSTRAINT_NOT_APPLIED",
            [row.code for row in plan.assumed if row.uid == first.uid],
        )

    def test_an_inactive_row_is_excluded_and_not_scheduled(self):
        inactive, extensions = self._task(1)
        inactive["active"] = False
        schedule, _, _ = migrate(_document([(inactive, extensions), self._task(2)]))
        plan = self._plan(schedule)
        self._partition(plan, schedule)
        self.assertEqual(
            [row.code for row in plan.excluded if row.kind == "activity"],
            ["ACTIVITY_INACTIVE"],
        )

if __name__ == "__main__":
    unittest.main()
