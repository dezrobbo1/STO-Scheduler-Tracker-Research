"""The rollup against the summary dates the real files store (slice S6).

The question this answers is not "is the arithmetic right" -- ``test_rollup``
asks that -- but whether Microsoft Project derives a summary's span the same
way. It does: a summary runs from the earliest start beneath it to the latest
finish beneath it, and the rule needs nothing else.

The evidence is the *triage*, not the count. Every summary these files
disagree about has a leaf beneath it whose own dates disagree; not one summary
is wrong while everything under it is right. So the rollup is exact wherever
the pass beneath it is, and what remains is the forward pass's residue
(ADR-010), which is already recorded and already pinned elsewhere.

The real schedules live outside the repository; ``STO_REQUIRE_BOILER=1`` turns
their absence into a failure instead of a skip, which is what a gate run sets.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sto.core.engine import build_plan, forward_pass, roll_up
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
}
if os.environ.get("STO_REQUIRE_BOILER") == "1":
    absent = sorted(name for name, path in FIXTURES.items() if not path.is_file())
    if absent:
        raise RuntimeError(f"STO_REQUIRE_BOILER=1 but these are not here: {absent}")


def _available():
    available = {name: path for name, path in FIXTURES.items() if path.is_file()}
    if not available:
        raise unittest.SkipTest("no real schedule fixture is available")
    return available

#: Summaries whose span the rollup reproduces exactly, per file, and the
#: summaries it does not. Pinned so that closing the forward pass's residue
#: raises these numbers deliberately rather than passing unnoticed.
EXPECTED = {
    "boiler_before": {"rolled": 94, "empty": 1, "exact": 75},
    "kiln": {"rolled": 86, "empty": 4, "exact": 36},
    "calciner": {"rolled": 219, "empty": 0, "exact": 206},
}


def _rolled(path: Path):
    schedule, _, _ = migrate(import_mspdi(str(path)))
    start = schedule.project.start or datetime(2026, 8, 1)
    plan = build_plan(schedule, (start - timedelta(days=60), start + timedelta(days=365)))
    forward = forward_pass(plan.network, snap_milestones=plan.snap_milestones)
    times = forward.by_uid()
    rollup = roll_up(
        plan.wbs_children,
        {uid: (row.early_start, row.early_finish) for uid, row in times.items()},
    )
    return schedule, plan, times, rollup


class RollupAgreementTests(unittest.TestCase):
    def test_every_summary_is_answered_or_named_empty(self):
        for name, path in _available().items():
            with self.subTest(name):
                _, plan, _, rollup = _rolled(path)
                answered = {row.uid for row in rollup.spans} | set(rollup.empty)
                self.assertEqual(answered, set(plan.wbs_children))

    def test_the_counts_are_what_they_are(self):
        for name, path in _available().items():
            with self.subTest(name):
                schedule, plan, _, rollup = _rolled(path)
                observations = {node.uid: node.source_observations for node in schedule.wbs_nodes}
                exact = 0
                for row in rollup.spans:
                    stored = observations.get(row.uid)
                    if stored is None or stored.start is None:
                        continue
                    exact += (
                        plan.to_datetime(row.start) == stored.start
                        and plan.to_datetime(row.finish) == stored.finish
                    )
                self.assertEqual(
                    {
                        "rolled": len(rollup.spans),
                        "empty": len(rollup.empty),
                        "exact": exact,
                    },
                    EXPECTED[name],
                )

    def test_no_summary_is_wrong_while_everything_beneath_it_is_right(self):
        """The claim the rule rests on, asked of all three files.

        A rollup that disagreed with a stored summary while every leaf under
        it agreed would mean Project derives the span some other way. None
        does, on any file here.
        """

        for name, path in _available().items():
            with self.subTest(name):
                schedule, plan, times, rollup = _rolled(path)
                activities = {a.uid: a for a in schedule.activities}
                observations = {node.uid: node.source_observations for node in schedule.wbs_nodes}
                children = plan.wbs_children

                def leaves(uid):
                    out = []
                    for child in children.get(uid, ()):
                        out.extend(leaves(child) if child in children else [child])
                    return out

                def agrees(uid):
                    row = times.get(uid)
                    stored = activities[uid].source_observations if uid in activities else None
                    if row is None or stored is None or stored.start is None:
                        return None
                    return (
                        plan.to_datetime(row.early_start) == stored.start
                        and plan.to_datetime(row.early_finish) == stored.finish
                    )

                unexplained = []
                for row in rollup.spans:
                    stored = observations.get(row.uid)
                    if stored is None or stored.start is None:
                        continue
                    if (
                        plan.to_datetime(row.start) == stored.start
                        and plan.to_datetime(row.finish) == stored.finish
                    ):
                        continue
                    if all(agrees(leaf) is not False for leaf in leaves(row.uid)):
                        unexplained.append(row.uid)
                self.assertEqual(unexplained, [], "a summary differs with every leaf agreeing")


if __name__ == "__main__":
    unittest.main()
