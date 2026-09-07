"""The eight findings of the reviews after PR #33 and PR #34, each pinned.

`AGENTS.md` answers the first automated review pass in full. PR #33 merged
five minutes before its review landed and PR #34's arrived on the open
branch; the eight findings between them are each fixed, and each has one test
here that fails on the code as it was. They are grouped by where the defect
lived, not by review.

Two were about the two passes disagreeing on the progress policy; two about a
free-float edge read differently from how the forward pass read it; two about
a labelled assumption that was not labelled, or was labelled per edge instead
of per row; one about a valid spelling of a source flag; and one about the
driver replay flooring a lead-placed task at the project start.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from calculation_fixture import _activity, _document, _relationship

from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import (
    BackwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
)
from sto.core.model.enums import ProgressPolicy, RelationshipType
from sto.core.model.migrate.sto_v011 import migrate

CONTINUOUS = CompiledIntervals.of(((0, 400),))


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-post-residue-review/{name}")


def activity(name, duration, calendar=CONTINUOUS, **fields) -> PlannedActivity:
    return PlannedActivity(uid(name), duration, calendar, **fields)


def link(name, predecessor, successor, type=RelationshipType.FS, lag=0, lag_calendar=None):
    return PlannedRelationship(
        uid(name), uid(predecessor), uid(successor), type, lag, lag_calendar
    )


def network(*activities, relationships=(), project_start=0, status_time=None):
    return Network(
        activities=tuple(activities),
        relationships=tuple(relationships),
        project_start=project_start,
        horizon=400,
        status_time=status_time,
    )


class PolicyTravelsOnTheForwardPassTests(unittest.TestCase):
    """PR #33, findings one and two: the backward pass and the policy."""

    def _network(self):
        # A holds B under retained logic; under override the edge is released.
        # C is a second successor of A so that the release moves no late date:
        # A's late finish is C's late start either way.
        return network(
            activity("A", 10),
            activity("B", 10, actual_start=0, remaining_duration=5),
            activity("C", 15),
            relationships=(link("R1", "A", "B"), link("R2", "A", "C")),
            status_time=20,
        )

    def test_the_backward_pass_reads_the_policy_from_the_forward_pass(self):
        net = self._network()
        forward = forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        self.assertIs(forward.progress_policy, ProgressPolicy.PROGRESS_OVERRIDE)
        backward = backward_pass(net, forward)
        # The defect: defaulting the policy a second time walked the edge the
        # forward pass had released.
        self.assertEqual(backward.overridden_relationships, (uid("R1"),))
        self.assertEqual(
            backward_pass(net, forward, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
            .fingerprint,
            backward.fingerprint,
        )

    def test_naming_a_different_policy_is_refused(self):
        net = self._network()
        forward = forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        with self.assertRaises(BackwardPassError) as raised:
            backward_pass(net, forward, progress_policy=ProgressPolicy.RETAINED_LOGIC)
        self.assertEqual(raised.exception.code, "SCHEDULE_POLICY_MISMATCH")

    def test_a_released_edge_that_moves_no_late_date_still_moves_the_fingerprint(self):
        net = self._network()
        retained = forward_pass(net, progress_policy=ProgressPolicy.RETAINED_LOGIC)
        override = forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        # The status date floors B's remaining work past A's finish under both
        # policies, so the edge is redundant: same early dates, same late dates.
        self.assertEqual(retained.fingerprint, override.fingerprint)
        first = backward_pass(net, retained)
        second = backward_pass(net, override)
        self.assertEqual(
            [(r.late_start, r.late_finish) for r in first.times],
            [(r.late_start, r.late_finish) for r in second.times],
        )
        self.assertEqual(first.overridden_relationships, ())
        self.assertEqual(second.overridden_relationships, (uid("R1"),))
        self.assertNotEqual(first.fingerprint, second.fingerprint)


class FreeFloatReadsEdgesAsTheForwardPassDidTests(unittest.TestCase):
    """PR #33 finding three and PR #34 finding five: the anchor and the lag."""

    def test_an_ss_edge_out_of_started_work_is_anchored_on_the_actual_start(self):
        # A began at 0; its remaining work resumes at the status date, 10. B
        # is a zero-lag SS successor and started when A did. B is exactly on
        # time, so A's free float on that edge is zero -- not minus ten, which
        # is what anchoring the edge at the remaining start reported.
        net = network(
            activity("A", 20, actual_start=0, remaining_duration=10),
            activity("B", 5),
            relationships=(link("R1", "A", "B", RelationshipType.SS),),
            status_time=10,
        )
        forward = forward_pass(net)
        rows = forward.by_uid()
        self.assertEqual(rows[uid("A")].remaining_start, 10)
        self.assertEqual((rows[uid("B")].early_start, rows[uid("B")].early_finish), (0, 5))
        floats = float_analysis(net, forward, backward_pass(net, forward))
        self.assertEqual(floats.by_uid()[uid("A")].free_float, 0)

    def test_a_lag_with_no_calendar_falls_back_to_the_scheduling_calendar(self):
        # B is placed on a calendar that opens at 100 and its float is measured
        # on the continuous one. The forward pass consumed the lag on B's
        # scheduling calendar (10 -> 100 -> 120); the free float must read the
        # same edge the same way, or it reports ninety units of slack that A
        # does not have.
        opens_late = CompiledIntervals.of(((100, 400),))
        net = network(
            activity("A", 10),
            activity("B", 10, opens_late, measure_calendar=CONTINUOUS),
            relationships=(link("R1", "A", "B", lag=20),),
        )
        forward = forward_pass(net)
        self.assertEqual(forward.by_uid()[uid("B")].early_start, 120)
        floats = float_analysis(net, forward, backward_pass(net, forward))
        self.assertEqual(floats.by_uid()[uid("A")].free_float, 0)


class DriverReplayFloorsWhereTheBoundsDidTests(unittest.TestCase):
    """PR #34 finding four: a lead-placed task before the project start."""

    def test_the_finish_bound_that_moved_a_pre_project_task_is_its_driver(self):
        # A sits at the project start, 100. Two leads place C before it: FS
        # with a lead of 50 bounds C's start at 60, FF with a lead of 30
        # bounds its finish at 80. The start bound alone would put C at
        # 60-70; the finish bound moved it to 70-80, so the FF edge drove.
        # Replaying against the project start instead of the calendar floor
        # placed the trial span at 90-100, past the finish bound, and credited
        # the start edge.
        net = network(
            activity("A", 10),
            activity("C", 10),
            relationships=(
                link("R1", "A", "C", RelationshipType.FS, lag=-50),
                link("R2", "A", "C", RelationshipType.FF, lag=-30),
            ),
            project_start=100,
        )
        forward = forward_pass(net)
        row = forward.by_uid()[uid("C")]
        self.assertEqual((row.early_start, row.early_finish), (70, 80))
        self.assertEqual(row.driving_relationship_uid, uid("R2"))


def _plan(document):
    schedule, _, _ = migrate(document)
    start = datetime(2026, 1, 5)
    return schedule, build_plan(schedule, (start - timedelta(days=7), start + timedelta(days=60)))


def _task(number, *, calendar_ref=None, active=True, **fields):
    hour = 8 + number
    return _activity(
        number,
        start=f"2026-01-05T{hour:02d}:00:00",
        finish=f"2026-01-05T{hour + 1:02d}:00:00",
        duration_seconds=3600,
        calendar_ref=calendar_ref,
        active=active,
        **fields,
    )


class PlanLabelsWhatItAssumesTests(unittest.TestCase):
    """PR #34 findings one and two: the assumed list counts rows and says why."""

    def _lag_assumptions(self, plan):
        return [row for row in plan.assumed if row.code == "RELATIONSHIP_LAG_ON_PROJECT_CALENDAR"]

    def test_a_lag_consumed_on_the_project_calendar_is_labelled(self):
        schedule, plan = _plan(
            _document([_task(1), _task(2)], relationships=[_relationship(1, 1, 2, lag=600)])
        )
        labelled = self._lag_assumptions(plan)
        self.assertEqual(len(labelled), 1)
        self.assertEqual(labelled[0].kind, "relationship")
        self.assertEqual(labelled[0].uid, schedule.relationships[0].uid)
        self.assertEqual(plan.assumed_by_code()["RELATIONSHIP_LAG_ON_PROJECT_CALENDAR"], 1)

    def test_a_lag_on_the_successors_own_calendar_is_measured_not_assumed(self):
        _, plan = _plan(
            _document(
                [_task(1), _task(2, calendar_ref="calendar:1")],
                relationships=[_relationship(1, 1, 2, lag=600)],
            )
        )
        self.assertEqual(self._lag_assumptions(plan), [])

    def test_zero_lag_touches_no_calendar_and_is_not_labelled(self):
        _, plan = _plan(_document([_task(1), _task(2)], relationships=[_relationship(1, 1, 2)]))
        self.assertEqual(self._lag_assumptions(plan), [])

    def test_a_successor_of_several_inactive_tasks_is_labelled_once(self):
        schedule, plan = _plan(
            _document(
                [_task(1, active=False), _task(2, active=False), _task(3)],
                relationships=[_relationship(1, 1, 3), _relationship(2, 2, 3)],
            )
        )
        rows = [row for row in plan.assumed if row.code == "ACTIVITY_SUCCESSOR_OF_INACTIVE"]
        successor = next(a.uid for a in schedule.activities if a.code == "3")
        self.assertEqual([row.uid for row in rows], [successor])
        self.assertEqual(plan.assumed_by_code()["ACTIVITY_SUCCESSOR_OF_INACTIVE"], 1)


class IgnoreResourceCalendarSpellingsTests(unittest.TestCase):
    """PR #34 finding three: ``xsd:boolean`` has two spellings of set."""

    def _flag(self, text):
        schedule, _, _ = migrate(_document([_task(1, ignore_resource_calendar=text)]))
        return schedule.activities[0].source_fields.get("ignore_resource_calendar_source")

    def test_both_spellings_of_set_are_carried(self):
        self.assertEqual(self._flag("1"), "1")
        self.assertEqual(self._flag("true"), "1")
        self.assertEqual(self._flag("True"), "1")

    def test_neither_spelling_of_clear_is(self):
        self.assertIsNone(self._flag("0"))
        self.assertIsNone(self._flag("false"))


if __name__ == "__main__":
    unittest.main()
