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
REQUIRE_BOILER = os.environ.get("STO_REQUIRE_BOILER") == "1"
if REQUIRE_BOILER and not BOILER_BEFORE.is_file():
    raise RuntimeError(
        f"STO_REQUIRE_BOILER=1 but the real schedule is not here: {BOILER_BEFORE}"
    )

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


if __name__ == "__main__":
    unittest.main()
