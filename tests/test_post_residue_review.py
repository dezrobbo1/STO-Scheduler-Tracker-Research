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

The second pass of the same reviewer, on the commit that answered the first,
raised five more; the 2026-09-07 comprehensive review reproduced every one.
They are the last five classes here: an explicit canonical lag policy that the
Microsoft rule reinterpreted; a measuring calendar with no working time that
measured every float as zero; a backward pass that did not carry its policy,
so the float could combine two passes run under different ones; an assumption
recorded for a row that was then excluded; and an edge below the calendar
floor reported as the driver of a task it did not move.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from calculation_fixture import _activity, _calendar, _document, _relationship

from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import (
    BackwardPassError,
    CriticalityError,
    ForwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
)
from sto.core.model.enums import LagCalendar, ProgressPolicy, RelationshipType
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


def _resource(number, calendar):
    return {
        "id": f"resource:{number}",
        "source_order": number,
        "external_references": [],
        "name": f"Sensitive resource {number}",
        "calendar_ref": f"calendar:{calendar}",
    }


def _assignment(number, task, resource):
    return {
        "id": f"assignment:{number}",
        "source_order": number,
        "task_ref": f"task:{task}",
        "resource_ref": f"resource:{resource}",
        "units_source": 1,
        "work_source": {"raw": "PT1H", "seconds": 3600, "parse_status": "parsed"},
        "actual_work_source": {"raw": "PT0S", "seconds": 0, "parse_status": "parsed"},
        "remaining_work_source": {"raw": "PT1H", "seconds": 3600, "parse_status": "parsed"},
        "percent_work_complete_source": 0,
        "work_contour_source": 0,
        "extension_refs": [],
    }


def _hour_task(number, start_hour, **fields):
    return _activity(
        number,
        start=f"2026-01-05T{start_hour:02d}:00:00",
        finish=f"2026-01-05T{start_hour + 1:02d}:00:00",
        duration_seconds=3600,
        **fields,
    )


class ExplicitLagPolicyIsPreservedTests(unittest.TestCase):
    """Second pass, finding one: the Microsoft rule applies to the inherited policy.

    The project calendar runs 08:00-16:00 and the successor's resource 10:00-18:00.
    The predecessor finishes at 09:00 with an hour of lag. Consumed on the project
    calendar -- Microsoft Project's rule for a successor with no task calendar --
    the lag ends at 10:00 and the successor starts then. A canonical schedule
    that *explicitly* says the lag runs on the successor's calendar means the
    calendar the successor is scheduled on, which opens at 10:00, so the lag
    ends at 11:00. The plan applied the Microsoft rule to both.
    """

    def _schedule(self):
        document = _document(
            [_hour_task(1, 8), _hour_task(2, 10)],
            relationships=[_relationship(1, 1, 2, lag=600)],
            calendars=[
                _calendar(1, [("08:00:00", "16:00:00")]),
                _calendar(2, [("10:00:00", "18:00:00")]),
            ],
            resources=[_resource(1, 2)],
            assignments=[_assignment(1, 2, 1)],
        )
        schedule, _, _ = migrate(document)
        return schedule

    def _successor_start(self, schedule):
        start = datetime(2026, 1, 5)
        plan = build_plan(schedule, (start - timedelta(days=7), start + timedelta(days=60)))
        forward = forward_pass(plan.network)
        successor = next(a.uid for a in schedule.activities if a.code == "2")
        return plan, plan.to_datetime(forward.by_uid()[successor].early_start)

    def test_the_inherited_policy_takes_the_project_calendar_and_is_labelled(self):
        schedule = self._schedule()
        self.assertIs(schedule.relationships[0].lag_calendar, LagCalendar.INHERIT_PROJECT_POLICY)
        plan, start = self._successor_start(schedule)
        self.assertEqual(start, datetime(2026, 1, 5, 10, 0))
        self.assertEqual(plan.assumed_by_code().get("RELATIONSHIP_LAG_ON_PROJECT_CALENDAR"), 1)

    def test_an_explicit_successor_policy_takes_the_successors_scheduling_calendar(self):
        schedule = self._schedule()
        explicit = replace(
            schedule,
            relationships=(replace(schedule.relationships[0], lag_calendar=LagCalendar.SUCCESSOR),),
        )
        plan, start = self._successor_start(explicit)
        self.assertEqual(start, datetime(2026, 1, 5, 11, 0))
        self.assertNotIn("RELATIONSHIP_LAG_ON_PROJECT_CALENDAR", plan.assumed_by_code())


class EmptyMeasuringCalendarIsRefusedTests(unittest.TestCase):
    """Second pass, finding four: slack cannot be measured on no working time."""

    def test_the_plan_excludes_a_row_whose_measuring_calendar_is_empty(self):
        # The project calendar has no working time at all; the task's resource
        # does. The task was scheduled on the resource's calendar and its float
        # measured on the project's, where every difference is zero working
        # time -- zero total float, zero free float, critical.
        empty = _calendar(1, [("08:00:00", "16:00:00")])
        for day in empty["week_days"]:
            day["working"] = False
            day["working_times"] = []
        schedule, plan = _plan(
            _document(
                [_hour_task(1, 10)],
                calendars=[empty, _calendar(2, [("10:00:00", "18:00:00")])],
                resources=[_resource(1, 2)],
                assignments=[_assignment(1, 1, 1)],
            )
        )
        self.assertEqual(plan.network.activities, ())
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_MEASURE_CALENDAR_EMPTY": 1})
        self.assertEqual(plan.excluded[0].uid, schedule.activities[0].uid)

    def test_a_directly_built_network_refuses_it_too(self):
        net = network(activity("A", 10, measure_calendar=CompiledIntervals.of(())))
        with self.assertRaises(ForwardPassError) as raised:
            net.validate()
        self.assertEqual(raised.exception.code, "SCHEDULE_MEASURE_CALENDAR_EMPTY")


class TheBackwardPassCarriesItsPolicyTests(unittest.TestCase):
    """Second pass, finding three: the float refuses passes under different policies.

    The network from ``OverrideReachesTheBackwardPassTests``: a two-hundred-unit
    predecessor of work under way from the status date. Under override the edge
    is released; under retained logic it binds. A backward pass computed from
    the retained-logic forward pass, handed to the float beside the override
    forward pass, walked the released edge and reported minus one hundred of
    free float on the predecessor. Both passes were over one network, so the
    fingerprint check let it through.
    """

    def _network(self):
        return network(
            activity("A", 200),
            activity("B", 40, actual_start=50, remaining_duration=10),
            relationships=(link("R1", "A", "B"),),
            status_time=100,
        )

    def test_the_policy_travels_on_the_backward_pass_and_into_its_fingerprint(self):
        net = self._network()
        retained = backward_pass(net, forward_pass(net, progress_policy=ProgressPolicy.RETAINED_LOGIC))
        override = backward_pass(net, forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE))
        self.assertIs(retained.progress_policy, ProgressPolicy.RETAINED_LOGIC)
        self.assertIs(override.progress_policy, ProgressPolicy.PROGRESS_OVERRIDE)
        self.assertNotEqual(retained.fingerprint, override.fingerprint)

    def test_mixed_policy_passes_are_refused_by_the_float(self):
        net = self._network()
        retained_forward = forward_pass(net, progress_policy=ProgressPolicy.RETAINED_LOGIC)
        retained_backward = backward_pass(net, retained_forward)
        override_forward = forward_pass(net, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        with self.assertRaises(CriticalityError) as raised:
            float_analysis(net, override_forward, retained_backward)
        self.assertEqual(raised.exception.code, "SCHEDULE_POLICY_MISMATCH")
        # The consistent pair still answers, and A holds nothing under override.
        consistent = float_analysis(net, override_forward, backward_pass(net, override_forward))
        self.assertEqual(consistent.by_uid()[uid("A")].free_float, 0)


class AssumptionsDescribeScheduledRowsOnlyTests(unittest.TestCase):
    """Second pass, finding two: an excluded row rests on no assumption."""

    def test_a_multi_resource_row_excluded_later_is_not_assumed(self):
        # Two resources on two calendars would put the row on their union and
        # label it; a start-no-earlier-than constraint with no date then
        # excludes it. The label was appended before the exclusion and
        # survived it, so ``assumed_by_code`` counted a row that was never
        # scheduled.
        row, extensions = _hour_task(1, 10)
        row["constraint_type_source"] = 4
        schedule, plan = _plan(
            _document(
                [(row, extensions)],
                calendars=[
                    _calendar(1, [("08:00:00", "16:00:00")]),
                    _calendar(2, [("10:00:00", "18:00:00")]),
                ],
                resources=[_resource(1, 1), _resource(2, 2)],
                assignments=[_assignment(1, 1, 1), _assignment(2, 1, 2)],
            )
        )
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_CONSTRAINT_INCOMPLETE": 1})
        self.assertEqual(plan.assumed, ())

    def test_a_multi_resource_row_that_is_scheduled_is_still_assumed(self):
        schedule, plan = _plan(
            _document(
                [_hour_task(1, 10)],
                calendars=[
                    _calendar(1, [("08:00:00", "16:00:00")]),
                    _calendar(2, [("10:00:00", "18:00:00")]),
                ],
                resources=[_resource(1, 1), _resource(2, 2)],
                assignments=[_assignment(1, 1, 1), _assignment(2, 1, 2)],
            )
        )
        self.assertEqual(plan.assumed_by_code(), {"ACTIVITY_RESOURCE_CALENDARS_UNITED": 1})
        self.assertEqual(plan.assumed[0].uid, plan.network.activities[0].uid)


class AnEdgeBelowTheFloorIsNotADriverTests(unittest.TestCase):
    """Second pass, finding five: a bound the calendar overrides drove nothing."""

    def test_a_lead_that_reaches_below_the_calendar_floor_is_cleared(self):
        # A sits at the project start, 50-60. C's calendar opens at 100. The
        # lead of 50 bounds C's start at 10, which is below C's floor, so C is
        # placed at 100-110 exactly as it would be with no edge at all. The
        # edge was still reported as its driver.
        opens_late = CompiledIntervals.of(((100, 400),))
        net = network(
            activity("A", 10),
            activity("C", 10, opens_late),
            relationships=(
                link("R1", "A", "C", RelationshipType.FS, lag=-50, lag_calendar=CONTINUOUS),
            ),
            project_start=50,
        )
        row = forward_pass(net).by_uid()[uid("C")]
        self.assertEqual((row.early_start, row.early_finish), (100, 110))
        self.assertIsNone(row.driving_relationship_uid)

    def test_a_lead_that_stays_above_the_floor_still_drives(self):
        opens_late = CompiledIntervals.of(((100, 400),))
        net = network(
            activity("A", 10),
            activity("C", 10, opens_late),
            relationships=(
                link("R1", "A", "C", RelationshipType.FS, lag=50, lag_calendar=CONTINUOUS),
            ),
            project_start=50,
        )
        row = forward_pass(net).by_uid()[uid("C")]
        self.assertEqual((row.early_start, row.early_finish), (110, 120))
        self.assertEqual(row.driving_relationship_uid, uid("R1"))


if __name__ == "__main__":
    unittest.main()
