"""Synthetic RC01 production boundary; never uses a customer schedule."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

from scripts.evidence.p1_g2_baseline_diagnostics import _load
from scripts.evidence.p1_g2_rc01_networked_v3_oracle import reference
from sto.core.engine.plan import build_plan
from sto.core.engine.forward import forward_pass
from sto.core.engine.backward import backward_pass
from sto.core.model.entities import Duration
from sto.core.model.enums import RelationshipType
from sto.core.engine.validate import validate_result
from sto.core.engine import float_analysis


FIXTURE = Path(__file__).resolve().parent / "fixtures/P1-G2-RC01-NETWORKED-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V3-R6.xml"


def schedule():
    return _load(FIXTURE.read_bytes())


def calculate(source):
    start = source.project.start
    plan = build_plan(source, (start - timedelta(days=90), start + timedelta(days=365)))
    early = forward_pass(plan.network, snap_milestones=plan.snap_milestones,
                         progress_policy=plan.progress_policy)
    late = backward_pass(plan.network, early, snap_milestones=plan.snap_milestones,
                         progress_policy=plan.progress_policy)
    return plan, early.by_uid(), late.by_uid()


def by_name(source, name):
    return next(row for row in source.activities if row.name == "V3-" + name)


class Rc01AssignmentEnvelopeProductionTests(unittest.TestCase):
    def test_forward_backward_networked_shapes_and_controls(self):
        source = schedule()
        plan, early, late = calculate(source)
        oracle = reference()
        for name in ("A", "A-ORDER-TWIN", "B", "C", "C-CALENDAR-IDENTITY-TWIN",
                     "D", "E", "F", "ADJACENT-C", "ADJACENT-B", "GAP"):
            with self.subTest(name=name):
                task = by_name(source, name)
                self.assertIsNotNone(plan.network.activity_by_uid()[task.uid].assignment_envelope)
                actual_early, actual_late = early[task.uid], late[task.uid]
                expected = oracle[name]
                self.assertEqual(plan.to_datetime(actual_early.early_start), expected["early_start"])
                self.assertEqual(plan.to_datetime(actual_early.early_finish), expected["early_finish"])
                self.assertEqual(plan.to_datetime(actual_late.late_start), expected["late_start"])
                self.assertEqual(plan.to_datetime(actual_late.late_finish), expected["late_finish"])
        for name in ("A-PRE", "A-POST", "D-POST", "D-POST-LONG", "FINISH-DRIVER"):
            with self.subTest(control=name):
                task = by_name(source, name)
                self.assertIsNone(plan.network.activity_by_uid()[task.uid].assignment_envelope)
                self.assertEqual(plan.to_datetime(early[task.uid].early_finish), oracle[name]["early_finish"])
        d = by_name(source, "D")
        long_branch = by_name(source, "D-POST-LONG")
        self.assertEqual(late[d.uid].driving_relationship_uid,
                         next(edge.uid for edge in source.relationships
                              if edge.predecessor_uid == d.uid and edge.successor_uid == long_branch.uid))
        self.assertGreater(late[d.uid].late_start, early[d.uid].early_start)

    def test_assignment_order_is_irrelevant(self):
        source = schedule()
        original = calculate(source)
        reversed_order = calculate(replace(source, assignments=tuple(reversed(source.assignments))))
        self.assertEqual(original[0].network.fingerprint(), reversed_order[0].network.fingerprint())
        self.assertEqual(original[1], reversed_order[1])
        self.assertEqual(original[2], reversed_order[2])

    def test_source_delays_are_preserved_and_unknown_or_duplicate_fails_closed(self):
        source = schedule()
        task = by_name(source, "C")
        assigned = next(row for row in source.assignments if row.activity_uid == task.uid)
        self.assertEqual(assigned.source_fields["delay_tenths_minutes_source"], "0")
        self.assertEqual(assigned.source_fields["leveling_delay_tenths_minutes_source"], "0")
        uri = "{http://schemas.microsoft.com/project}"
        for field, action in (("Delay", "remove"), ("Delay", "nonzero"),
                              ("Delay", "duplicate"), ("LevelingDelay", "remove"),
                              ("LevelingDelay", "nonzero"), ("LevelingDelay", "duplicate")):
            with self.subTest(field=field, action=action):
                document = ET.fromstring(FIXTURE.read_bytes())
                row = next(row for row in document.findall(f"./{uri}Assignments/{uri}Assignment")
                           if row.findtext(f"{uri}UID") == assigned.external_refs[0].uid)
                element = row.find(f"{uri}{field}")
                self.assertIsNotNone(element)
                if action == "remove":
                    row.remove(element)
                elif action == "nonzero":
                    element.text = "10"
                else:
                    ET.SubElement(row, f"{uri}{field}").text = "10"
                changed = _load(ET.tostring(document))
                plan, _, _ = calculate(changed)
                self.assertIsNone(plan.network.activity_by_uid()[task.uid].assignment_envelope)
                self.assertIn("ACTIVITY_RESOURCE_CALENDARS_UNITED",
                              [a.code for a in plan.assumed if a.uid == task.uid])

    def test_network_fingerprint_commits_to_assignment_work_and_calendar(self):
        source = schedule()
        original, _, _ = calculate(source)
        task = by_name(source, "C")
        original_activity = original.network.activity_by_uid()[task.uid]
        altered = replace(original_activity, assignment_envelope=(
            replace(original_activity.assignment_envelope[0], work_duration=7200),
            original_activity.assignment_envelope[1],
        ))
        amended = replace(original.network, activities=tuple(
            altered if row.uid == task.uid else row for row in original.network.activities))
        self.assertNotEqual(original.network.fingerprint(), amended.fingerprint())
        self.assertEqual(original_activity.duration, altered.duration)

    def test_independent_validator_accepts_envelope_and_rejects_corrupted_span(self):
        source = schedule()
        plan = build_plan(source, (source.project.start - timedelta(days=90),
                                   source.project.start + timedelta(days=365)))
        early = forward_pass(plan.network)
        late = backward_pass(plan.network, early)
        floats = float_analysis(plan.network, early, late,
                                threshold=plan.critical_float_threshold)
        self.assertEqual(validate_result(plan.network, early, late, floats), ())
        task = by_name(source, "C")
        broken = replace(early.by_uid()[task.uid], early_finish=early.by_uid()[task.uid].early_finish + 1)
        altered = replace(early, times=tuple(broken if row.uid == task.uid else row
                                              for row in early.times))
        self.assertIn("EARLY_ASSIGNMENT_ENVELOPE_INVALID",
                      [row.code for row in validate_result(plan.network, altered, late, floats)])

    def test_ineligible_assignment_and_task_inputs_keep_union_assumption(self):
        source = schedule()
        task = by_name(source, "C")
        assigned = next(row for row in source.assignments if row.activity_uid == task.uid)
        changes = (
            replace(assigned, source_fields={**assigned.source_fields, "delay_tenths_minutes_source": "1"}),
            replace(assigned, source_fields={**assigned.source_fields, "leveling_delay_tenths_minutes_source": "1"}),
            replace(assigned, source_fields={k: v for k, v in assigned.source_fields.items()
                                                    if k != "delay_tenths_minutes_source"}),
            replace(assigned, work=replace(assigned.work, actual_seconds=1)),
            replace(assigned, work=replace(assigned.work, budgeted_seconds=1,
                                            remaining_seconds=1)),
        )
        for changed in changes:
            with self.subTest(assignment=changed):
                altered = replace(source, assignments=tuple(changed if a.uid == assigned.uid else a
                                                             for a in source.assignments))
                plan, _, _ = calculate(altered)
                self.assertIsNone(plan.network.activity_by_uid()[task.uid].assignment_envelope)
                self.assertIn("ACTIVITY_RESOURCE_CALENDARS_UNITED",
                              [a.code for a in plan.assumed if a.uid == task.uid])
        for changed in (replace(task, actual_start=source.project.start),
                        replace(task, calendar_uid=source.project.default_calendar_uid),
                        replace(task, source_fields={**task.source_fields, "ignore_resource_calendar_source": "1"})):
            with self.subTest(task=changed):
                altered = replace(source, activities=tuple(changed if a.uid == task.uid else a
                                                            for a in source.activities))
                plan = build_plan(altered, (source.project.start - timedelta(days=90),
                                            source.project.start + timedelta(days=365)))
                if task.uid in plan.network.activity_by_uid():
                    self.assertIsNone(plan.network.activity_by_uid()[task.uid].assignment_envelope)

    def test_non_fs_or_nonzero_lag_falls_back(self):
        source = schedule()
        task = by_name(source, "C")
        edge = next(row for row in source.relationships if row.successor_uid == task.uid)
        for changed in (replace(edge, type=RelationshipType.SS),
                        replace(edge, lag=Duration(seconds=3600))):
            altered = replace(source, relationships=tuple(changed if r.uid == edge.uid else r
                                                          for r in source.relationships))
            plan = build_plan(altered, (source.project.start - timedelta(days=90),
                                        source.project.start + timedelta(days=365)))
            self.assertIsNone(plan.network.activity_by_uid()[task.uid].assignment_envelope)


if __name__ == "__main__":
    unittest.main()
