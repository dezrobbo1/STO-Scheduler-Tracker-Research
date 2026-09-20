"""The clean UID 227 repeat for the controlled BOILER progress experiment.

The customer schedules remain external. This module is bound to
P1-NATIVE-PROGRESS-BOILER-UID227-V1 and applies the comparison contract that
was committed before the returned Microsoft Project file existed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
import os
from pathlib import Path
import unittest

from tests.controlled_native_progress_evidence import (
    DIRECT_CONTROLLED_EDIT,
    ENGINE_NATIVE_AGREEMENT,
    EXPLICIT_EXCLUSION,
    PROJECT_DERIVED_PROGRESS_INPUT,
    UNCHANGED,
    classify_controlled_transition,
    classify_selected_progress,
    unique_rows,
)
from tests.real_fixture_guard import verify_available
from tests.test_controlled_native_progress_boiler import (
    _activities,
    _activity_static,
    _calculate,
    _calendar_fingerprint,
    _duration_seconds,
    _engine,
    _excluded,
    _load,
    _observed,
    _project_signature,
    _relationship_signature,
    _resource_fingerprint,
    _source_uid,
    _wbs_fingerprint,
)


BEFORE = Path(
    os.environ.get(
        "STO_BOILER_BEFORE",
        "/home/dez/sto-fixtures/boiler-before-no-progress.xml",
    )
)
NATIVE = Path(
    os.environ.get(
        "STO_BOILER_CONTROLLED_NATIVE_REPEAT",
        "/home/dez/sto-fixtures/P1-CONTROLLED-NATIVE-PROGRESS-UID227-RETURNED.xml",
    )
)
FIXTURES = {"boiler_before": BEFORE, "controlled_native_repeat": NATIVE}
verify_available(FIXTURES)

if os.environ.get("STO_REQUIRE_CONTROLLED_NATIVE_REPEAT") == "1":
    for _role, _path in FIXTURES.items():
        if not _path.is_file():
            raise RuntimeError(
                "STO_REQUIRE_CONTROLLED_NATIVE_REPEAT=1 but the clean repeat "
                f"oracle is not here: {_path}"
            )

_PRESENT = all(path.is_file() for path in FIXTURES.values())
TARGET_SOURCE_UID = "227"
TARGET_ACTUAL_START = datetime.fromisoformat("2026-09-14T11:00:00")
TARGET_REMAINING_SECONDS = 14_400
TARGET_BUILD = "16.0.20228.20186"


@unittest.skipUnless(
    _PRESENT,
    "the UID 227 controlled repeat is absent; set "
    "STO_REQUIRE_CONTROLLED_NATIVE_REPEAT=1",
)
class ControlledNativeProgressRepeatBoilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = _load(BEFORE)
        cls.native = _load(NATIVE)
        cls.before_rows = _activities(cls.before)
        cls.native_rows = _activities(cls.native)
        selected = cls.before_rows[TARGET_SOURCE_UID]
        cls.controlled_selected = replace(
            selected,
            actual_start=TARGET_ACTUAL_START,
            remaining_duration=replace(
                selected.remaining_duration,
                seconds=TARGET_REMAINING_SECONDS,
            ),
        )
        cls.controlled = replace(
            cls.before,
            activities=tuple(
                cls.controlled_selected if row.uid == selected.uid else row
                for row in cls.before.activities
            ),
        )
        cls.base_plan, cls.base_forward, cls.base_result = _calculate(cls.before)
        cls.control_plan, cls.control_forward, cls.control_result = _calculate(
            cls.controlled
        )
        cls.native_plan, cls.native_forward, cls.native_result = _calculate(cls.native)

    def test_build_identity_and_exact_control_are_preserved(self):
        self.assertEqual(self.native.snapshots[0].application_version, TARGET_BUILD)
        self.assertEqual(len(self.before_rows), 460)
        self.assertEqual(set(self.before_rows), set(self.native_rows))
        self.assertEqual(
            _relationship_signature(self.before),
            _relationship_signature(self.native),
        )
        self.assertEqual(_project_signature(self.before), _project_signature(self.native))
        self.assertEqual(
            _calendar_fingerprint(self.before), _calendar_fingerprint(self.native)
        )
        self.assertEqual(
            _resource_fingerprint(self.before), _resource_fingerprint(self.native)
        )
        self.assertEqual(_wbs_fingerprint(self.before), _wbs_fingerprint(self.native))

        before = self.before_rows[TARGET_SOURCE_UID]
        native = self.native_rows[TARGET_SOURCE_UID]
        self.assertIsNone(before.actual_start)
        self.assertEqual(native.actual_start, TARGET_ACTUAL_START)
        self.assertIsNone(native.actual_finish)
        self.assertEqual(_duration_seconds(before.remaining_duration), 28_800)
        self.assertEqual(_duration_seconds(native.remaining_duration), 14_400)
        self.assertEqual(_duration_seconds(before.actual_duration), 0)
        self.assertEqual(_duration_seconds(native.actual_duration), 0)
        self.assertEqual((native.suspend, native.resume), (TARGET_ACTUAL_START,) * 2)
        for plan in (self.control_plan, self.native_plan):
            self.assertNotIn(
                "ACTIVITY_IN_PROGRESS_LATE_DATES_ASSUMED",
                {
                    row.code
                    for row in plan.assumed
                    if row.uid
                    in {
                        self.controlled_selected.uid,
                        native.uid,
                    }
                },
            )

        for source in sorted(self.before_rows, key=int):
            old, new = self.before_rows[source], self.native_rows[source]
            selected = source == TARGET_SOURCE_UID
            self.assertEqual(
                _activity_static(self.before, old, selected=selected),
                _activity_static(self.native, new, selected=selected),
                source,
            )
            if selected:
                continue
            self.assertEqual(
                (
                    old.actual_start,
                    old.actual_finish,
                    old.actual_duration,
                    old.suspend,
                    old.resume,
                    old.remaining_duration,
                    old.percent_complete,
                    old.planned_duration,
                    old.planned_work,
                    old.active,
                    old.manual,
                ),
                (
                    new.actual_start,
                    new.actual_finish,
                    new.actual_duration,
                    new.suspend,
                    new.resume,
                    new.remaining_duration,
                    new.percent_complete,
                    new.planned_duration,
                    new.planned_work,
                    new.active,
                    new.manual,
                ),
                source,
            )

    def test_requested_edit_and_quantitative_normalizations_reconcile(self):
        before = self.before_rows[TARGET_SOURCE_UID]
        native = self.native_rows[TARGET_SOURCE_UID]
        before_assignment = next(
            row for row in self.before.assignments if row.activity_uid == before.uid
        )
        native_assignment = next(
            row for row in self.native.assignments if row.activity_uid == native.uid
        )
        reasons = dict(
            classify_selected_progress(
                before_actual_start=before.actual_start,
                after_actual_start=native.actual_start,
                expected_actual_start=TARGET_ACTUAL_START,
                before_remaining=_duration_seconds(before.remaining_duration),
                after_remaining=_duration_seconds(native.remaining_duration),
                expected_remaining=TARGET_REMAINING_SECONDS,
                before_planned=_duration_seconds(before.planned_duration),
                after_planned=_duration_seconds(native.planned_duration),
                before_actual=_duration_seconds(before.actual_duration),
                after_actual=_duration_seconds(native.actual_duration),
                after_percent_permille=native.percent_complete.duration_permille,
                after_actual_finish=native.actual_finish,
                assignment_units_permille=native_assignment.units.budgeted_permille,
                before_task_work=_duration_seconds(before.planned_work),
                after_task_work=_duration_seconds(native.planned_work),
                before_assignment_work=before_assignment.work.budgeted_seconds,
                after_assignment_work=native_assignment.work.budgeted_seconds,
                before_assignment_actual_work=before_assignment.work.actual_seconds,
                after_assignment_actual_work=native_assignment.work.actual_seconds,
                after_assignment_remaining_work=native_assignment.work.remaining_seconds,
            )
        )
        self.assertEqual(
            reasons,
            {DIRECT_CONTROLLED_EDIT: 2, PROJECT_DERIVED_PROGRESS_INPUT: 3},
        )

    def test_fixed_contract_reconciles_every_result_field(self):
        summary = classify_controlled_transition(
            _observed(self.before_rows),
            _observed(self.native_rows),
            _engine(self.before, self.base_result),
            _engine(self.before, self.control_result),
            _engine(self.native, self.native_result),
            _excluded(self.base_plan, self.before),
        )
        self.assertEqual((summary.added_rows, summary.removed_rows), (0, 0))
        self.assertEqual(summary.field_slots, 4_140)
        self.assertEqual(
            dict(summary.classifications),
            {
                ENGINE_NATIVE_AGREEMENT: 43,
                EXPLICIT_EXCLUSION: 81,
                UNCHANGED: 4_016,
            },
        )
        self.assertEqual(summary.unexplained, ())
        self.assertEqual(summary.unexplained_count, 0)

    def test_assignment_outputs_move_without_input_corruption(self):
        before_assignments = unique_rows(
            (_source_uid(row), row) for row in self.before.assignments
        )
        native_assignments = unique_rows(
            (_source_uid(row), row) for row in self.native.assignments
        )
        self.assertEqual(set(before_assignments), set(native_assignments))
        target_uid = self.before_rows[TARGET_SOURCE_UID].uid
        before_activity_sources = {
            row.uid: _source_uid(row) for row in self.before.activities
        }
        native_activity_sources = {
            row.uid: _source_uid(row) for row in self.native.activities
        }
        before_resource_sources = {
            row.uid: _source_uid(row) for row in self.before.resources
        }
        native_resource_sources = {
            row.uid: _source_uid(row) for row in self.native.resources
        }
        changed_spans = 0
        for source in sorted(before_assignments, key=int):
            old, new = before_assignments[source], native_assignments[source]
            selected = old.activity_uid == target_uid
            self.assertEqual(
                before_activity_sources.get(old.activity_uid),
                native_activity_sources.get(new.activity_uid),
                source,
            )
            self.assertEqual(
                before_resource_sources.get(old.resource_uid),
                native_resource_sources.get(new.resource_uid),
                source,
            )
            self.assertEqual(old.units, new.units, source)
            self.assertEqual(old.unassigned_placeholder, new.unassigned_placeholder, source)
            if selected:
                self.assertEqual(old.work.actual_seconds, 0)
                self.assertEqual(new.work.actual_seconds, 0)
                self.assertEqual(new.work.budgeted_seconds, TARGET_REMAINING_SECONDS)
                self.assertEqual(new.work.remaining_seconds, TARGET_REMAINING_SECONDS)
            else:
                self.assertEqual(old.work, new.work, source)
                self.assertEqual(
                    old.percent_work_complete_permille,
                    new.percent_work_complete_permille,
                    source,
                )
            changed_spans += (old.start, old.finish) != (new.start, new.finish)
        self.assertEqual(changed_spans, 7)

    def test_predicted_changed_cohort_and_dispositions_are_exact(self):
        changed = {
            uid
            for uid in self.base_result
            if self.base_result[uid] != self.control_result[uid]
        }
        successors = self.base_plan.network.successors()
        selected_uid = self.before_rows[TARGET_SOURCE_UID].uid
        reachable = set()
        frontier = [selected_uid]
        while frontier:
            current = frontier.pop()
            for edge in successors[current]:
                if edge.successor_uid not in reachable:
                    reachable.add(edge.successor_uid)
                    frontier.append(edge.successor_uid)
        moved_downstream = {
            uid
            for uid in reachable
            if self.base_result[uid][:2] != self.control_result[uid][:2]
        }
        self.assertEqual(len(changed), 12)
        self.assertEqual(len(moved_downstream), 6)
        dispositions = Counter(
            "EXCLUDED_CODED"
            if row.uid not in self.control_result
            else "ASSUMED_LABELLED"
            if row.uid in {
                item.uid
                for item in self.control_plan.assumed
                if item.kind == "activity"
            }
            or row.uid in self.control_forward.unbounded_starts
            else "SUPPORTED_CALCULATED"
            for row in self.before.activities
        )
        self.assertEqual(
            dispositions,
            Counter(
                {
                    "SUPPORTED_CALCULATED": 433,
                    "ASSUMED_LABELLED": 18,
                    "EXCLUDED_CODED": 9,
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
