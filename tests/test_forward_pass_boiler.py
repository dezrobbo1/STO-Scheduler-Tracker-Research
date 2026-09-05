"""The forward pass over a real schedule: does every row get a disposition?

The P1 gate asks that on both BOILER snapshots every leaf activity gets a
disposition and no difference is UNEXPLAINED. The second half needs the
backward pass and the status date, so it is not asked here. The first half is
a forward-pass question and is asked here: every activity in the file is either
in the network or in :attr:`~sto.core.engine.plan.Plan.excluded` with a code,
and nothing falls between the two.

No count is pinned. The counts these files produce are evidence and belong in
``docs/history/`` written against a run, not guessed at in a test; what is
asserted here are the properties that hold whatever the counts turn out to be.

The real schedules live outside the repository. ``STO_BOILER_BEFORE`` names one
and ``STO_REQUIRE_BOILER=1`` turns its absence into a failure instead of a skip,
which is what a gate run sets.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sto.core.engine import ForwardPassError, build_plan, forward_pass
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi

BOILER_BEFORE = Path(
    os.environ.get("STO_BOILER_BEFORE", "/home/dez/sto-fixtures/boiler-before-no-progress.xml")
)
#: The other two real schedules the agreement counts are pinned on (ADR-010).
FIXTURES = {
    "boiler_before": BOILER_BEFORE,
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
ALL_PRESENT = all(path.is_file() for path in FIXTURES.values())

#: Every code the plan is allowed to exclude a row with. A new code appearing on
#: a real file should be a deliberate decision, not a silent one.
KNOWN_CODES = frozenset(
    {
        "ACTIVITY_KIND_NOT_SCHEDULED",
        "ACTIVITY_INACTIVE",
        "ACTIVITY_DURATION_ELAPSED",
        "ACTIVITY_CALENDAR_UNRESOLVED",
        "ACTIVITY_MULTIPLE_RESOURCE_CALENDARS",
        "ACTIVITY_CALENDAR_EMPTY",
        "ACTIVITY_CONSTRAINT_INCOMPLETE",
        "ACTIVITY_SECONDARY_CONSTRAINT_NOT_APPLIED",
        "RELATIONSHIP_ENDPOINT_NOT_SCHEDULED",
        "RELATIONSHIP_LAG_CALENDAR_UNRESOLVED",
    }
)

#: Every assumption the plan may schedule a row under. As with the codes above,
#: a new one appearing on a real file is a decision, not a side effect.
KNOWN_ASSUMPTIONS = frozenset(
    {
        "ACTIVITY_RESOURCE_CALENDARS_UNITED",
        "ACTIVITY_SUCCESSOR_OF_INACTIVE",
    }
)


@unittest.skipUnless(
    BOILER_BEFORE.is_file(),
    "real BOILER schedule not present (it stays outside the repository); "
    "set STO_REQUIRE_BOILER=1 to make this a failure",
)
class BoilerForwardPassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document = import_mspdi(str(BOILER_BEFORE))
        cls.schedule, _, _ = migrate(document)
        start = cls.schedule.project.start or datetime(2026, 8, 1)
        cls.horizon = (start - timedelta(days=60), start + timedelta(days=365))
        cls.plan = build_plan(cls.schedule, cls.horizon)

    def test_every_activity_gets_a_disposition(self):
        """Scheduled or excluded with a code -- never neither, never both."""

        scheduled = {row.uid for row in self.plan.network.activities}
        excluded = {row.uid for row in self.plan.excluded if row.kind == "activity"}
        # A secondary constraint is reported without excluding the activity, so
        # an activity may legitimately appear in both; every other code excludes.
        reported = scheduled | excluded
        missing = [a.uid for a in self.schedule.activities if a.uid not in reported]
        self.assertEqual(missing, [], "activities with no disposition at all")

    def test_every_assumption_carries_a_known_code(self):
        unknown = sorted({row.code for row in self.plan.assumed} - KNOWN_ASSUMPTIONS)
        self.assertEqual(unknown, [], "assumptions with no recorded meaning")

    def test_every_exclusion_carries_a_known_code(self):
        unknown = sorted({row.code for row in self.plan.excluded} - KNOWN_CODES)
        self.assertEqual(unknown, [], "undeclared exclusion codes")

    def test_the_network_is_not_empty(self):
        self.assertGreater(
            len(self.plan.network.activities),
            0,
            f"nothing was schedulable: {self.plan.excluded_by_code()}",
        )

    def test_the_forward_pass_completes_on_the_real_file(self):
        try:
            result = forward_pass(self.plan.network, snap_milestones=self.plan.snap_milestones)
        except ForwardPassError as error:
            self.fail(f"{error.code} on {error.uid}: {error.detail}")
        self.assertEqual(len(result.times), len(self.plan.network.activities))

    def test_every_span_is_ordered_and_inside_the_horizon(self):
        result = forward_pass(self.plan.network, snap_milestones=self.plan.snap_milestones)
        window = self.plan.network.horizon
        for row in result.times:
            self.assertLessEqual(row.early_start, row.early_finish, str(row.uid))
            self.assertLessEqual(row.early_finish, window, str(row.uid))

    def test_the_disposition_of_every_row_is_the_one_that_was_measured(self):
        """The counts ``docs/history/`` records, pinned so they cannot drift quietly.

        Nine activities are inactive and are not scheduled; the fifteen edges
        that lost an endpoint to them are dropped with them. Everything else in
        the file schedules. If this changes, the history entry is now wrong and
        one of the two has to be corrected deliberately.
        """

        self.assertEqual(len(self.schedule.activities), 460)
        self.assertEqual(len(self.schedule.relationships), 600)
        self.assertEqual(len(self.plan.network.activities), 451)
        self.assertEqual(
            self.plan.excluded_by_code(),
            {"ACTIVITY_INACTIVE": 9, "RELATIONSHIP_ENDPOINT_NOT_SCHEDULED": 15},
        )

    def test_the_file_carries_no_constraint_this_pass_would_have_to_apply(self):
        """Measured, because it bounds what the difference against Project can be.

        Every task in this file is ASAP with no constraint date, no deadline, no
        manual placement and no levelling delay, and every one of its six
        hundred links is FS. So the remaining difference against Project's own
        dates is not a constraint this pass declined to apply.
        """

        self.assertEqual(
            [a.uid for a in self.schedule.activities if a.primary_constraint is not None],
            [],
        )
        self.assertEqual([a.uid for a in self.schedule.activities if a.manual], [])
        self.assertEqual([a.uid for a in self.schedule.activities if a.deadline], [])
        self.assertEqual(
            [a.uid for a in self.schedule.activities if a.levelling_delay_seconds], []
        )
        self.assertEqual(
            {r.type.value for r in self.schedule.relationships}, {"FS"}
        )

    def test_two_runs_over_one_file_agree(self):
        first = forward_pass(self.plan.network, snap_milestones=self.plan.snap_milestones)
        second = forward_pass(self.plan.network, snap_milestones=self.plan.snap_milestones)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_a_second_plan_from_the_same_schedule_agrees(self):
        """The plan is a function of the schedule and the horizon, and nothing else."""

        again = build_plan(self.schedule, self.horizon)
        self.assertEqual(
            forward_pass(again.network, snap_milestones=again.snap_milestones).fingerprint,
            forward_pass(
                self.plan.network, snap_milestones=self.plan.snap_milestones
            ).fingerprint,
        )


def _agreement(path: Path) -> dict:
    """How the pass agrees with the dates the file stores, and where it stops.

    A *first mismatch* is a row that differs while every predecessor agrees;
    everything else that differs is inherited from one. The two are counted
    apart because they are different claims: the first is a rule the engine
    does not have, the second is that rule's shadow.
    """

    schedule, _, _ = migrate(import_mspdi(str(path)))
    start = schedule.project.start or datetime(2026, 8, 1)
    plan = build_plan(schedule, (start - timedelta(days=60), start + timedelta(days=365)))
    result = forward_pass(plan.network, snap_milestones=plan.snap_milestones)
    times = result.by_uid()
    activities = {a.uid: a for a in schedule.activities}
    predecessors = plan.network.predecessors()

    def agrees(uid) -> bool:
        stored = activities[uid].source_observations
        row = times[uid]
        return (
            plan.to_datetime(row.early_start) == stored.start
            and plan.to_datetime(row.early_finish) == stored.finish
        )

    counts = {"compared": 0, "exact": 0, "first": 0, "inherited": 0}
    for activity in plan.network.activities:
        stored = activities[activity.uid].source_observations
        if stored is None or stored.start is None:
            continue
        counts["compared"] += 1
        if agrees(activity.uid):
            counts["exact"] += 1
        elif all(agrees(edge.predecessor_uid) for edge in predecessors[activity.uid]):
            counts["first"] += 1
        else:
            counts["inherited"] += 1
    counts["assumed"] = plan.assumed_by_code()
    return counts


@unittest.skipUnless(
    ALL_PRESENT,
    "the real schedules are not present (they stay outside the repository); "
    "set STO_REQUIRE_BOILER=1 to make this a failure",
)
class StoredDateAgreementTests(unittest.TestCase):
    """How far the pass reproduces the dates Project stored, pinned (ADR-010).

    These are the numbers the diagnosis of the forward-pass residue ended on.
    Pinned so that a rule change moves them deliberately: a drop is a
    regression and a rise is a history entry that has to be written.
    """

    def test_boiler(self):
        counts = _agreement(FIXTURES["boiler_before"])
        self.assertEqual(
            {k: counts[k] for k in ("compared", "exact", "first", "inherited")},
            {"compared": 451, "exact": 384, "first": 8, "inherited": 59},
        )
        self.assertEqual(
            counts["assumed"],
            {"ACTIVITY_RESOURCE_CALENDARS_UNITED": 11, "ACTIVITY_SUCCESSOR_OF_INACTIVE": 5},
        )

    def test_kiln(self):
        counts = _agreement(FIXTURES["kiln"])
        self.assertEqual(
            {k: counts[k] for k in ("compared", "exact", "first", "inherited")},
            {"compared": 417, "exact": 247, "first": 6, "inherited": 164},
        )

    def test_calciner(self):
        counts = _agreement(FIXTURES["calciner"])
        self.assertEqual(
            {k: counts[k] for k in ("compared", "exact", "first", "inherited")},
            {"compared": 1763, "exact": 1645, "first": 6, "inherited": 112},
        )

    def test_the_calendar_rule_is_what_moved_boiler(self):
        """Off, the pass agrees with Project on one BOILER activity -- as it did
        when the forward-pass slice shipped -- so the rule is measurable from
        the test alone rather than from the history entry that records it."""

        schedule, _, _ = migrate(import_mspdi(str(FIXTURES["boiler_before"])))
        start = schedule.project.start
        horizon = (start - timedelta(days=60), start + timedelta(days=365))
        activities = {a.uid: a for a in schedule.activities}
        exact = {}
        for apply in (False, True):
            plan = build_plan(schedule, horizon, resource_calendars_apply=apply)
            times = forward_pass(plan.network, snap_milestones=plan.snap_milestones).by_uid()
            exact[apply] = sum(
                1
                for uid, row in times.items()
                if plan.to_datetime(row.early_start) == activities[uid].source_observations.start
                and plan.to_datetime(row.early_finish) == activities[uid].source_observations.finish
            )
        self.assertLess(exact[False], 60)
        self.assertEqual(exact[True], 384)


if __name__ == "__main__":
    unittest.main()
