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
    FROM_PROJECT_START,
    BackwardPassError,
    PlanError,
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
from sto.core.model.enums import (
    ConstraintType,
    LagCalendar,
    ProgressPolicy,
    RelationshipType,
)
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
        """The edge is read on the calendar the passes consumed it on.

        B is placed on a calendar with a gap and its float is measured on the
        continuous one. The forward pass consumes the twenty-unit lag on B's
        *scheduling* calendar: ten units of 100-110, then ten more from 200, so
        B starts at 210. Carrying that bound back over the same calendar says A
        may finish as late as 100; carrying it back over the measuring calendar
        would say 190, which is not true -- A finishing at 190 puts B at 220.

        The expected value changed with C2. It was written as zero under the
        rule that shifted the lag forward and measured the leftover gap, and
        that rule understates as badly as it overstates: A really can finish
        ninety units later than it does without moving B, because the lag
        cannot begin to be consumed until the calendar opens.
        """

        gapped = CompiledIntervals.of(((100, 110), (200, 400)))
        net = network(
            activity("A", 10),
            activity("B", 10, gapped, measure_calendar=CONTINUOUS),
            relationships=(link("R1", "A", "B", lag=20),),
        )
        forward = forward_pass(net)
        self.assertEqual(forward.by_uid()[uid("B")].early_start, 210)
        floats = float_analysis(net, forward, backward_pass(net, forward))
        self.assertEqual(floats.by_uid()[uid("A")].free_float, 90)


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


def _ff_relationship(uid_, predecessor, successor, lag=0):
    row = _relationship(uid_, predecessor, successor, lag)
    row["type"] = "FF"
    row["source_type_code"] = 0
    return row


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


class UnresolvedCalendarStillExcludesOneRowTests(unittest.TestCase):
    """Third pass: a broken calendar reference excludes a row, not the schedule.

    The exclusion this asserts is the reason the plan distinguishes an
    unresolved calendar from an absent one at all, and no file in the estate
    carries one, so nothing exercised the branch until the assumption value
    was added to every other return and not to this one.
    """

    def test_one_broken_reference_excludes_its_row_and_leaves_the_rest(self):
        # The migration still turns an unresolved source reference into "no
        # calendar" (the review's F01, owed to C1), so the broken reference is
        # set on the canonical row here: it is the plan's distinction being
        # tested, not the importer's.
        schedule, _, _ = migrate(_document([_hour_task(1, 9), _hour_task(2, 10)]))
        missing = uid("absent-calendar")
        broken = replace(schedule.activities[1], calendar_uid=missing)
        schedule = replace(schedule, activities=(schedule.activities[0], broken))
        start = datetime(2026, 1, 5)
        plan = build_plan(schedule, (start - timedelta(days=7), start + timedelta(days=60)))
        self.assertEqual(plan.excluded_by_code(), {"ACTIVITY_CALENDAR_UNRESOLVED": 1})
        self.assertEqual(plan.excluded[0].uid, broken.uid)
        self.assertIn(str(missing), plan.excluded[0].detail)
        self.assertEqual([row.uid for row in plan.network.activities], [schedule.activities[0].uid])


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


class DatesDoNotDependOnTheCompiledWindowTests(unittest.TestCase):
    """The review that landed after PR #34 merged: a finish-only successor.

    Once a task with predecessors stopped being floored at the project start,
    an unstarted task whose predecessors are all FF or SF had *no* bound on
    its start, and the missing side fell back to the calendar's first working
    moment. That is not a schedule input -- it is wherever the caller chose to
    compile from -- so such a task moved whenever the horizon widened while
    nothing about the schedule changed. The start side now falls back to the
    project start, which is where Microsoft Project puts an ASAP task nothing
    else places; the finish side still falls back to the calendar, because an
    unbounded finish is implied by the start bound plus the duration and
    flooring it at the project start drags a lead-placed task back to it --
    the fifty-six BOILER rows of ADR-010.

    No file in the estate exercises this: KILN's fifty-eight finish-only rows
    and CALCINER's fifty-three all carry a finish bound late enough that the
    duration, not the floor, places them. The agreement counts are unchanged.
    """

    def _placed(self, calendar_opens: int) -> tuple[int, int]:
        calendar = CompiledIntervals.of(((calendar_opens, 400),))
        net = network(
            activity("A", 10, calendar),
            # Long enough that starting at the floor already satisfies the
            # finish bound, which is when the floor decides the answer.
            activity("B", 200, calendar),
            relationships=(link("R1", "A", "B", RelationshipType.FF),),
            project_start=100,
        )
        row = forward_pass(net).by_uid()[uid("B")]
        return row.early_start, row.early_finish

    def test_a_finish_only_successor_sits_at_the_project_start(self):
        self.assertEqual(self._placed(0), (100, 300))

    def test_and_says_that_is_where_it_came_from(self):
        """The fallback is an assumption, so the row is not allowed to hide it.

        ADR-010 measured that the project start bounds only a task with no
        predecessors, and this activity has one. No file in the estate settles
        where such a row belongs, so the result says where it was placed from
        and names no relationship as the reason -- the FF edge is satisfied by
        the span the floor produces and drove nothing.
        """

        calendar = CompiledIntervals.of(((0, 400),))
        net = network(
            activity("A", 10, calendar),
            activity("B", 200, calendar),
            relationships=(link("R1", "A", "B", RelationshipType.FF),),
            project_start=100,
        )
        row = forward_pass(net).by_uid()[uid("B")]
        self.assertEqual(row.source, FROM_PROJECT_START)
        self.assertIsNone(row.driving_relationship_uid)

    def test_the_pass_reports_the_row_it_placed_on_the_fallback(self):
        """The rows resting on the guess, named by the only thing that knows.

        Three attempts at deciding this from the plan alone each named rows the
        fallback never reached -- work already started, a row pinned by a
        must-start-on constraint, a row a start-no-earlier-than raised past the
        floor. The plan can see that no edge bounds a row's start; it cannot
        see what then placed the row. The pass can, and reports it.
        """

        calendar = CompiledIntervals.of(((0, 400),))

        def placed(**successor) -> tuple:
            net = network(
                activity("A", 10, calendar),
                activity("B", 200, calendar, **successor),
                relationships=(link("R1", "A", "B", RelationshipType.FF),),
                project_start=100,
            )
            return forward_pass(net).unbounded_starts

        self.assertEqual(placed(), (uid("B"),))
        # A finish constraint that raises a bound the span already satisfies
        # changes the row's reported source without moving its start, so
        # reading the label off the source hid the fallback behind it.
        self.assertEqual(
            placed(constraint_type=ConstraintType.FNET, constraint_coordinate=150),
            (uid("B"),),
        )
        # Each of these places the row itself, so the fallback never reaches it.
        self.assertEqual(
            placed(constraint_type=ConstraintType.SNET, constraint_coordinate=150), ()
        )
        self.assertEqual(
            placed(constraint_type=ConstraintType.MSO, constraint_coordinate=150), ()
        )
        self.assertEqual(placed(actual_start=50, remaining_duration=10), ())

    def test_a_row_the_fallback_supplies_but_does_not_place_is_not_reported(self):
        """The bound is not the question; whether it changed the answer is.

        Every activity in the estate whose predecessors bound only its finish
        takes the fallback as its start bound, and not one of them is placed
        by it: the finish bound and the row's own duration decide, and the
        answer is the same with the calendar's floor in the fallback's place.
        Reporting those rows would name a hundred and eleven assumptions the
        schedule does not rest on.
        """

        calendar = CompiledIntervals.of(((0, 400),))
        net = network(
            activity("A", 10, calendar),
            # Short enough that the FF bound, not the floor, places it.
            activity("B", 10, calendar),
            relationships=(link("R1", "A", "B", RelationshipType.FF, lag=100, lag_calendar=CONTINUOUS),),
            project_start=100,
        )
        result = forward_pass(net)
        self.assertEqual(result.by_uid()[uid("B")].early_start, 200)
        self.assertEqual(result.unbounded_starts, ())

    def test_a_row_its_predecessors_place_is_not_reported(self):
        net = network(
            activity("A", 10),
            activity("B", 10),
            relationships=(link("R1", "A", "B"),),
            project_start=100,
        )
        self.assertEqual(forward_pass(net).unbounded_starts, ())

    def test_an_unsnapped_milestone_keeps_the_edge_that_placed_it(self):
        """The replay has to place a milestone the way the pass does.

        With ``snap_milestones`` off a milestone sits exactly on its bound,
        gap or no gap, but the replay went through ``earliest_span``, which
        always snaps a zero-duration span forward. The project start here lies
        in a gap that reopens after the finish bound, so the snapped replay
        landed past the bound, concluded the edge was already satisfied, and
        cleared a driver that had really placed the row.
        """

        gapped = CompiledIntervals.of(((0, 5), (20, 400)))
        net = network(
            activity("A", 5),
            activity("M", 0, gapped),
            relationships=(link("R1", "A", "M", RelationshipType.FF, lag_calendar=CONTINUOUS),),
            project_start=10,
        )
        row = forward_pass(net, snap_milestones=False).by_uid()[uid("M")]
        self.assertEqual(row.early_start, 15)
        self.assertEqual(row.driving_relationship_uid, uid("R1"))

    def test_but_a_finish_bound_that_really_moves_it_still_drives(self):
        calendar = CompiledIntervals.of(((0, 400),))
        net = network(
            activity("A", 10, calendar),
            activity("C", 10, calendar),
            relationships=(link("R1", "A", "C", RelationshipType.FF, lag=100, lag_calendar=CONTINUOUS),),
            project_start=100,
        )
        row = forward_pass(net).by_uid()[uid("C")]
        self.assertEqual((row.early_start, row.early_finish), (200, 210))
        self.assertEqual(row.driving_relationship_uid, uid("R1"))

    def test_and_does_not_move_when_the_window_does(self):
        self.assertEqual(self._placed(0), self._placed(40))
        self.assertEqual(self._placed(0), self._placed(80))

    def test_a_lead_placed_task_is_still_not_dragged_to_the_project_start(self):
        # The rule this must not undo: an FS lead places a task before the
        # project start, and its unbounded *finish* side must not floor it.
        net = network(
            activity("A", 10),
            activity("C", 10),
            relationships=(
                link("R1", "A", "C", RelationshipType.FS, lag=-50, lag_calendar=CONTINUOUS),
            ),
            project_start=100,
        )
        row = forward_pass(net).by_uid()[uid("C")]
        self.assertEqual((row.early_start, row.early_finish), (60, 70))


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
