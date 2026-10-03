"""S7 execution facts and complete incremental/full semantic equivalence."""

from __future__ import annotations

import random
import os
import subprocess
import sys
import unittest
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import Network, NetworkError, PlannedActivity, PlannedRelationship, backward_pass, float_analysis, forward_pass
from sto.core.engine.incremental import recalculate_network
from sto.core.engine.plan import Plan
from sto.core.engine.result import project_result
from sto.core.engine.rollup import roll_up
from sto.core.execution import ExecutionChange, ExecutionError, apply_execution, calculate_state
from sto.core.hashing import canonical_sha256
from sto.core.model.codec import encode_schedule
from sto.core.model.entities import Assignment, Resource, TimeInterval
from sto.core.model.enums import CalendarType, ConstraintType, ProgressPolicy, RelationshipType
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi


SOURCE = Path(__file__).parent / "fixtures" / "synthetic-workspace-chain.mspdi.xml"
WINDOW = (datetime(2025, 12, 1), datetime(2027, 1, 1))


def source():
    return migrate(import_mspdi(str(SOURCE)))[0]


def change(schedule, uid, **facts):
    return ExecutionChange(activity_uid=uid, expected_hash=canonical_sha256(encode_schedule(schedule)), **facts)


class ExecutionTests(unittest.TestCase):
    def test_execution_preserves_disabled_resource_calendars_and_full_reference_context(self):
        schedule = source()
        task = schedule.activities[0]
        assigned_resource = uuid5(NAMESPACE_URL, "s7/afternoon-worker")
        resource_calendar = replace(
            schedule.calendars[0], uid=uuid5(NAMESPACE_URL, "s7/afternoon-resource"),
            type=CalendarType.RESOURCE,
            base_uid=schedule.calendars[0].uid,
            week=tuple(replace(day, intervals=(TimeInterval(13 * 3600, 17 * 3600),))
                       for day in schedule.calendars[0].week if day.day == 2),
        )
        schedule = replace(
            schedule, calendars=(*schedule.calendars, resource_calendar),
            activities=tuple(replace(row, source_fields={**row.source_fields,
                             "ignore_resource_calendar_source": "0"}) if row.uid == schedule.activities[1].uid
                             else row for row in schedule.activities),
            resources=(Resource(assigned_resource, calendar_uid=resource_calendar.uid),),
            assignments=(Assignment(uuid5(NAMESPACE_URL, "s7/assignment"),
                                    activity_uid=schedule.activities[1].uid,
                                    resource_uid=assigned_resource),),
        )
        baseline = calculate_state(schedule, WINDOW, resource_calendars_apply=False)
        command = change(schedule, task.uid, actual_start=datetime(2026, 1, 5, 9), remaining_seconds=3600)
        updated = apply_execution(baseline, command)
        reference = calculate_state(updated.schedule, WINDOW, resource_calendars_apply=False)
        self.assertFalse(updated.plan.resource_calendars_apply)
        self.assertFalse(reference.plan.resource_calendars_apply)
        self.assertEqual(updated.result, reference.result)
        self.assertEqual(updated.canonical_hash, reference.canonical_hash)
        self.assertEqual(updated.result.by_uid()[schedule.activities[1].uid],
                         reference.result.by_uid()[schedule.activities[1].uid])
        self.assertNotEqual(reference.result.by_uid()[schedule.activities[1].uid].early_start,
                            calculate_state(updated.schedule, WINDOW, resource_calendars_apply=True).result.by_uid()[schedule.activities[1].uid].early_start)

    def test_execution_preserves_explicit_epoch_in_full_reference(self):
        schedule = source()
        epoch = WINDOW[0] - timedelta(days=7)
        baseline = calculate_state(schedule, WINDOW, epoch=epoch)
        uid = next(row.uid for row in schedule.activities if baseline.result.by_uid()[row.uid].disposition == "scheduled")
        updated = apply_execution(baseline, change(schedule, uid, actual_start=datetime(2026, 1, 5, 9), remaining_seconds=3600))
        reference = calculate_state(updated.schedule, WINDOW, epoch=epoch)
        self.assertEqual(updated.plan.epoch, epoch)
        self.assertEqual(updated.result, reference.result)
        self.assertEqual(updated.canonical_hash, reference.canonical_hash)
        self.assertEqual(updated.canonical_hash, calculate_state(updated.schedule, WINDOW).canonical_hash)
        self.assertNotEqual(reference.plan.epoch, calculate_state(updated.schedule, WINDOW).plan.epoch)

    def test_execution_refuses_semantic_plan_context_drift(self):
        schedule = source()
        baseline = calculate_state(schedule, WINDOW)
        uid = schedule.activities[0].uid
        command = change(schedule, uid, actual_start=datetime(2026, 1, 5, 9), remaining_seconds=3600)
        altered_plan = replace(baseline.plan,
                               critical_float_threshold=baseline.plan.critical_float_threshold + 1)
        with self.assertRaises(ExecutionError) as caught:
            apply_execution(replace(baseline, plan=altered_plan), command)
        self.assertEqual(caught.exception.code, "EXECUTION_CONTEXT_CHANGED")
        self.assertEqual(baseline.canonical_hash, canonical_sha256(encode_schedule(schedule)))

    def test_start_remaining_finish_keeps_actual_history_and_matches_fresh_full(self):
        baseline = calculate_state(source(), WINDOW)
        uid = next(row.uid for row in baseline.schedule.activities if row.uid in baseline.result.by_uid() and baseline.result.by_uid()[row.uid].disposition == "scheduled")
        original = baseline.schedule.activity_by_uid()[uid]
        start = original.actual_start or datetime(2026, 1, 5, 9)
        begun = apply_execution(baseline, change(baseline.schedule, uid, actual_start=start, remaining_seconds=3600))
        self.assertEqual(begun.schedule.activity_by_uid()[uid].actual_start, start)
        self.assertEqual(begun.result.by_uid()[uid].state, "in_progress")
        self.assertEqual(begun.result, calculate_state(begun.schedule, WINDOW).result)
        updated = apply_execution(begun, change(begun.schedule, uid, remaining_seconds=1800))
        self.assertEqual(updated.schedule.activity_by_uid()[uid].actual_start, start)
        self.assertEqual(updated.result, calculate_state(updated.schedule, WINDOW).result)
        finished = apply_execution(updated, change(updated.schedule, uid, actual_finish=start + timedelta(hours=2), remaining_seconds=0))
        row = finished.result.by_uid()[uid]
        self.assertEqual((row.early_start, row.early_finish, row.late_start, row.late_finish), (start, start + timedelta(hours=2), start, start + timedelta(hours=2)))
        self.assertFalse(row.critical)
        self.assertEqual(finished.result, calculate_state(finished.schedule, WINDOW).result)
        other = next(item.uid for item in finished.schedule.activities
                     if item.uid != uid and finished.result.by_uid()[item.uid].disposition == "scheduled")
        after_other = apply_execution(finished, change(finished.schedule, other,
                                                       actual_start=start + timedelta(hours=2),
                                                       remaining_seconds=3600))
        self.assertEqual(after_other.result.by_uid()[uid], row)
        self.assertEqual(after_other.result, calculate_state(after_other.schedule, WINDOW).result)
        with self.assertRaises(ExecutionError) as caught:
            apply_execution(finished, change(finished.schedule, uid, remaining_seconds=1))
        self.assertEqual(caught.exception.code, "EXECUTION_ALREADY_COMPLETE")
        direct = apply_execution(baseline, change(baseline.schedule, uid,
                                                  actual_start=start,
                                                  actual_finish=start + timedelta(hours=2)))
        self.assertEqual(direct.schedule.activity_by_uid()[uid].remaining_duration.seconds, 0)
        self.assertEqual(direct.result, calculate_state(direct.schedule, WINDOW).result)

    def test_refuses_stale_history_and_invalid_transitions_with_codes(self):
        baseline = calculate_state(source(), WINDOW)
        uid = next(row.uid for row in baseline.schedule.activities if baseline.result.by_uid()[row.uid].disposition == "scheduled")
        start = datetime(2026, 1, 5, 9)
        cases = [
            (change(baseline.schedule, uid, actual_finish=start), "EXECUTION_FINISH_WITHOUT_START"),
            (change(baseline.schedule, uid, remaining_seconds=1), "EXECUTION_REMAINING_REQUIRES_START"),
            (change(baseline.schedule, uid, actual_start=start), "EXECUTION_REMAINING_REQUIRED"),
            (change(baseline.schedule, uid, actual_start=start, remaining_seconds=0), "EXECUTION_IN_PROGRESS_REMAINING_ZERO"),
            (change(baseline.schedule, uid, actual_start=start, actual_finish=start - timedelta(seconds=1), remaining_seconds=0), "EXECUTION_ACTUALS_INVERTED"),
            (change(baseline.schedule, uid, actual_start=start, actual_finish=start + timedelta(hours=1), remaining_seconds=1), "EXECUTION_FINISHED_REMAINING_NONZERO"),
            (change(baseline.schedule, uid, actual_start=start + timedelta(microseconds=1), remaining_seconds=3600), "EXECUTION_ACTUAL_TIME_INVALID"),
        ]
        for command, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(ExecutionError) as caught:
                    apply_execution(baseline, command)
                self.assertEqual(caught.exception.code, code)
        begun = apply_execution(baseline, change(baseline.schedule, uid, actual_start=start, remaining_seconds=3600))
        for command, code in [
            (change(baseline.schedule, uid, remaining_seconds=1800), "EXECUTION_STALE_VERSION"),
            (change(begun.schedule, uid, actual_start=start + timedelta(minutes=1), remaining_seconds=1800), "EXECUTION_ACTUAL_START_IMMUTABLE"),
            (change(begun.schedule, uid, actual_finish=start + timedelta(hours=1), remaining_seconds=1), "EXECUTION_FINISHED_REMAINING_NONZERO"),
        ]:
            with self.subTest(code=code):
                with self.assertRaises(ExecutionError) as caught:
                    apply_execution(begun, command)
                self.assertEqual(caught.exception.code, code)

    def test_refuses_unsupported_activity_policy_and_elapsed_remaining(self):
        schedule = source()
        baseline = calculate_state(schedule, WINDOW)
        uid = next(row.uid for row in schedule.activities if baseline.result.by_uid()[row.uid].disposition == "scheduled")
        command = change(schedule, uid, actual_start=datetime(2026, 1, 5, 9), remaining_seconds=3600)
        for altered, code in [
            (replace(schedule, activities=tuple(replace(row, active=False) if row.uid == uid else row for row in schedule.activities)), "EXECUTION_ACTIVITY_UNSUPPORTED"),
            (replace(schedule, activities=tuple(replace(row, remaining_duration=replace(row.remaining_duration, elapsed=True)) if row.uid == uid else row for row in schedule.activities)), "EXECUTION_ELAPSED_REMAINING_UNSUPPORTED"),
            (replace(schedule, project=replace(schedule.project, progress_policy=ProgressPolicy.ACTUAL_DATES)), "PROGRESS_POLICY_NOT_EVIDENCED"),
        ]:
            with self.subTest(code=code):
                state = calculate_state(altered, WINDOW)
                with self.assertRaises(ExecutionError) as caught:
                    apply_execution(state, replace(command, expected_hash=state.canonical_hash))
                self.assertEqual(caught.exception.code, code)

    def test_elapsed_planned_fallback_is_refused_without_changing_canonical_input(self):
        schedule = source()
        uid = schedule.activities[0].uid
        schedule = replace(schedule, activities=tuple(
            replace(row, planned_duration=replace(row.planned_duration, elapsed=True),
                    remaining_duration=None) if row.uid == uid else row
            for row in schedule.activities
        ))
        baseline = calculate_state(schedule, WINDOW)
        original_document = encode_schedule(schedule)
        original_hash = baseline.canonical_hash
        with self.assertRaises(ExecutionError) as caught:
            apply_execution(baseline, change(schedule, uid,
                                             actual_start=datetime(2026, 1, 5, 9),
                                             remaining_seconds=3600))
        self.assertEqual(caught.exception.code, "EXECUTION_ELAPSED_REMAINING_UNSUPPORTED")
        self.assertEqual(encode_schedule(schedule), original_document)
        self.assertEqual(canonical_sha256(encode_schedule(schedule)), original_hash)
        self.assertIsNone(baseline.schedule.activity_by_uid()[uid].remaining_duration)

    def test_non_elapsed_planned_fallback_still_creates_remaining_duration(self):
        schedule = source()
        uid = schedule.activities[0].uid
        schedule = replace(schedule, activities=tuple(
            replace(row, remaining_duration=None) if row.uid == uid else row
            for row in schedule.activities
        ))
        baseline = calculate_state(schedule, WINDOW)
        updated = apply_execution(baseline, change(schedule, uid,
                                                   actual_start=datetime(2026, 1, 5, 9),
                                                   remaining_seconds=3600))
        self.assertFalse(updated.schedule.activity_by_uid()[uid].remaining_duration.elapsed)
        self.assertNotEqual(updated.canonical_hash, baseline.canonical_hash)
        self.assertEqual(updated.result, calculate_state(updated.schedule, WINDOW).result)

    def test_hash_and_result_are_stable_across_process_hash_seeds(self):
        code = """from datetime import datetime
from sto.core.execution import calculate_state,apply_execution,ExecutionChange
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi
s=migrate(import_mspdi('tests/fixtures/synthetic-workspace-chain.mspdi.xml'))[0]
p=calculate_state(s,(datetime(2025,12,1),datetime(2027,1,1)))
u=next(r.uid for r in s.activities if p.result.by_uid()[r.uid].disposition=='scheduled')
q=apply_execution(p,ExecutionChange(u,p.canonical_hash,actual_start=datetime(2026,1,5,9),remaining_seconds=3600))
print(q.canonical_hash,q.result.fingerprint,q.recalculation.mode)
"""
        outputs = [subprocess.check_output([sys.executable, "-c", code], cwd=SOURCE.parents[2],
                                             env={**os.environ, "PYTHONPATH": "src", "PYTHONHASHSEED": seed})
                   for seed in ("1", "31", "999")]
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])


CAL = CompiledIntervals.of(((0, 3000),))
SHIFT = CompiledIntervals.of(tuple((i * 50, i * 50 + 40) for i in range(60)))


def network(seed):
    rng = random.Random(seed)
    count = rng.randrange(5, 15)
    rows = tuple(PlannedActivity(uuid5(NAMESPACE_URL, f"s7/{seed}/{i}"), rng.randrange(1, 15), CAL if seed % 3 else SHIFT) for i in range(count))
    edges = []
    for i in range(1, count):
        for j in range(i):
            if rng.randrange(5) == 0:
                edges.append(PlannedRelationship(uuid5(NAMESPACE_URL, f"s7/e/{seed}/{j}/{i}"), rows[j].uid, rows[i].uid, rng.choice(tuple(RelationshipType)), 0))
    return Network(rows, tuple(edges), 0, 3000, 1 if seed % 3 == 1 else None)


def semantic_result(net, forward, backward):
    """The full published semantic contract, including derived WBS/edge rows."""
    root = uuid5(NAMESPACE_URL, f"s7/root/{net.activities[0].uid}")
    child = uuid5(NAMESPACE_URL, f"s7/child/{net.activities[0].uid}")
    plan = Plan(net, datetime(2026, 1, 1), {},
                progress_policy=forward.progress_policy,
                wbs_children={root: (child, *[row.uid for row in net.activities[::2]]),
                              child: tuple(row.uid for row in net.activities[1::2])})
    floats = float_analysis(net, forward, backward)
    rolled = roll_up(plan.wbs_children, {uid: (row.early_start, row.early_finish)
                                         for uid, row in forward.by_uid().items()})
    return project_result(plan, forward, backward, floats, rolled,
                          canonical_hash=net.fingerprint(),
                          horizon=(datetime(2026, 1, 1), datetime(2026, 1, 2)))


class EquivalenceTests(unittest.TestCase):
    def test_predeclared_semantic_oracle_includes_passes_float_and_result_lineage(self):
        original = network(29)
        old_forward = forward_pass(original)
        old_backward = backward_pass(original, old_forward)
        changed = replace(original, activities=tuple(replace(row, actual_start=2, remaining_duration=3) if i == 0 else row for i, row in enumerate(original.activities)))
        result = recalculate_network(original, changed, old_forward, old_backward, changed.activities[0].uid)
        full_forward = forward_pass(changed)
        full_backward = backward_pass(changed, full_forward)
        self.assertEqual(result.forward, full_forward)
        self.assertEqual(result.backward, full_backward)
        self.assertEqual(float_analysis(changed, result.forward, result.backward), float_analysis(changed, full_forward, full_backward))

    def test_thousand_seeded_dags_with_sequential_execution_updates(self):
        modes = Counter()
        finishes = Counter()
        refusals = Counter()
        skipped_noops = 0
        for seed in range(1000):
            original = network(seed)
            policy = (ProgressPolicy.RETAINED_LOGIC, ProgressPolicy.PROGRESS_OVERRIDE, ProgressPolicy.NONE)[seed % 3]
            before = forward_pass(original, progress_policy=policy)
            late = backward_pass(original, before)
            rng = random.Random(seed + 40001)
            for step in range(2):
                # Some legal DAGs have no forecast for an arbitrary proposed
                # progress fact (e.g. SF/SS logic and an impossible late span).
                # Verify the same coded refusal, then try another seeded fact;
                # every one of the 1,000 networks still gets two accepted edits.
                candidates = list(range(len(original.activities)))
                rng.shuffle(candidates)
                for index in candidates:
                    row = original.activities[index]
                    replacement = replace(row, actual_start=before.by_uid()[row.uid].early_start, remaining_duration=max(1, row.duration - 1)) if row.actual_start is None else replace(row, remaining_duration=max(1, row.remaining_duration - 1))
                    if replacement == row:
                        skipped_noops += 1
                        continue
                    changed = replace(original, activities=tuple(replacement if i == index else value for i, value in enumerate(original.activities)))
                    try:
                        expected = forward_pass(changed, progress_policy=policy)
                        expected_late = backward_pass(changed, expected)
                    except NetworkError as refused:
                        with self.assertRaises(type(refused)) as caught:
                            recalculate_network(original, changed, before, late, row.uid)
                        self.assertEqual(caught.exception.code, refused.code)
                        refusals[refused.code] += 1
                        continue
                    break
                else:
                    self.fail(f"seed={seed}, step={step}: no supported execution candidate")
                with self.subTest(seed=seed, step=step):
                    self.assertNotEqual(replacement, row, "accepted execution candidate must change semantics")
                    self.assertNotEqual(changed, original)
                    computed = recalculate_network(original, changed, before, late, row.uid)
                    self.assertEqual(computed.forward, expected)
                    self.assertEqual(computed.backward, expected_late)
                    self.assertEqual(float_analysis(changed, computed.forward, computed.backward), float_analysis(changed, expected, expected_late))
                    self.assertEqual(semantic_result(changed, computed.forward, computed.backward),
                                     semantic_result(changed, expected, expected_late))
                    if expected.project_finish != before.project_finish:
                        self.assertEqual(computed.mode, "full_fallback")
                modes[computed.mode] += 1
                finishes[computed.forward.project_finish != before.project_finish] += 1
                original, before, late = changed, computed.forward, computed.backward
        self.assertEqual(sum(modes.values()), 2000)
        self.assertEqual(set(modes), {"incremental", "full_fallback"})
        self.assertEqual(set(finishes), {True, False})
        self.assertTrue(all(code.startswith("SCHEDULE_") for code in refusals))
        print(f"S7 campaign: seeds=0..999 accepted=2000 modes={dict(modes)} "
              f"finish_changed={dict(finishes)} refused_proposals={dict(refusals)} "
              f"skipped_noops={skipped_noops}", file=sys.stderr)

    def test_explicit_fallback_when_component_spans_network(self):
        original = Network((PlannedActivity(uuid5(NAMESPACE_URL, "a"), 3, CAL), PlannedActivity(uuid5(NAMESPACE_URL, "b"), 5, CAL)), (PlannedRelationship(uuid5(NAMESPACE_URL, "edge"), uuid5(NAMESPACE_URL, "a"), uuid5(NAMESPACE_URL, "b")),), 0, 3000)
        before = forward_pass(original)
        late = backward_pass(original, before)
        changed = replace(original, activities=(replace(original.activities[0], actual_start=1, remaining_duration=2), original.activities[1]))
        self.assertEqual(recalculate_network(original, changed, before, late, changed.activities[0].uid).mode, "full_fallback")

    def test_disconnected_component_recomputes_both_passes_without_running_full_network(self):
        first = PlannedActivity(uuid5(NAMESPACE_URL, "s7/a"), 3, CAL)
        second = PlannedActivity(uuid5(NAMESPACE_URL, "s7/b"), 4, CAL)
        long = PlannedActivity(uuid5(NAMESPACE_URL, "s7/long"), 20, CAL)
        edge = PlannedRelationship(uuid5(NAMESPACE_URL, "s7/a-b"), first.uid, second.uid)
        original = Network((first, second, long), (edge,), 0, 3000)
        before = forward_pass(original)
        late = backward_pass(original, before)
        changed = replace(original, activities=(replace(first, actual_start=1, remaining_duration=2), second, long))
        calculated = recalculate_network(original, changed, before, late, first.uid)
        self.assertEqual((calculated.mode, calculated.recalculated_activities), ("incremental", 2))
        self.assertEqual(calculated.forward, forward_pass(changed))
        self.assertEqual(calculated.backward, backward_pass(changed, forward_pass(changed)))

    def test_progress_constraint_reports_and_released_edges_survive_bounded_path(self):
        predecessor = PlannedActivity(uuid5(NAMESPACE_URL, "s7/pred"), 4, CAL)
        successor = PlannedActivity(uuid5(NAMESPACE_URL, "s7/succ"), 3, CAL,
                                    constraint_type=ConstraintType.SNET, constraint_coordinate=5)
        independent = PlannedActivity(uuid5(NAMESPACE_URL, "s7/longer"), 40, CAL)
        edge = PlannedRelationship(uuid5(NAMESPACE_URL, "s7/pred-succ"), predecessor.uid, successor.uid)
        original = Network((predecessor, successor, independent), (edge,), 0, 3000, 6)
        before = forward_pass(original, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        late = backward_pass(original, before)
        changed = replace(original, activities=(predecessor, replace(successor, actual_start=5, remaining_duration=3), independent))
        calculated = recalculate_network(original, changed, before, late, successor.uid)
        expected = forward_pass(changed, progress_policy=ProgressPolicy.PROGRESS_OVERRIDE)
        expected_late = backward_pass(changed, expected)
        self.assertEqual(calculated.mode, "incremental")
        self.assertEqual(calculated.forward, expected)
        self.assertEqual(calculated.backward, expected_late)
        self.assertEqual(calculated.backward.overridden_relationships, (edge.uid,))
        self.assertEqual(calculated.forward.deferred_constraints[0].activity_uid, successor.uid)
        self.assertEqual(semantic_result(changed, calculated.forward, calculated.backward),
                         semantic_result(changed, expected, expected_late))
