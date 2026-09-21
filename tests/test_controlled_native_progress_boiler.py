"""The controlled Project-native in-progress BOILER experiment.

The customer files stay outside git.  This module is deliberately bound to
P1-NATIVE-PROGRESS-BOILER-UID15-V1 and records the current truthful outcome:
the native run proves and fixes one started-work late-date rule, but three
fields remain unexplained under the comparison contract fixed before the run.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import unittest

from tests.controlled_native_progress_evidence import (
    BASELINE_MISMATCH,
    DIRECT_CONTROLLED_EDIT,
    ENGINE_NATIVE_AGREEMENT,
    EXPLICIT_EXCLUSION,
    PROJECT_DERIVED_PROGRESS_INPUT,
    RESULT_FIELDS,
    UNCHANGED,
    UNEXPLAINED,
    classify_controlled_transition,
    classify_selected_progress,
    unique_rows,
)
from tests.real_fixture_guard import verify_available

from sto.core.engine import backward_pass, build_plan, float_analysis, forward_pass
from sto.core.model.migrate.sto_v011 import migrate
from sto.legacy import import_mspdi


BEFORE = Path(
    os.environ.get(
        "STO_BOILER_BEFORE",
        "/home/dez/sto-fixtures/boiler-before-no-progress.xml",
    )
)
NATIVE = Path(
    os.environ.get(
        "STO_BOILER_CONTROLLED_NATIVE",
        "/home/dez/sto-fixtures/P1-CONTROLLED-NATIVE-PROGRESS-RETURNED.xml",
    )
)
FIXTURES = {"boiler_before": BEFORE, "controlled_native": NATIVE}
verify_available(FIXTURES)

if os.environ.get("STO_REQUIRE_CONTROLLED_NATIVE") == "1":
    for _role, _path in FIXTURES.items():
        if not _path.is_file():
            raise RuntimeError(
                "STO_REQUIRE_CONTROLLED_NATIVE=1 but the controlled oracle is not here: "
                f"{_path}"
            )

_PRESENT = all(path.is_file() for path in FIXTURES.values())
TARGET_SOURCE_UID = "15"
TARGET_ACTUAL_START = datetime.fromisoformat("2026-09-08T07:30:00")
TARGET_REMAINING_SECONDS = 3_600


def _source_uid(entity) -> str:
    refs = entity.external_refs
    if len(refs) != 1 or not refs[0].uid:
        raise ValueError("entity lacks exactly one source identity")
    return str(refs[0].uid)


def _duration_seconds(value) -> int | None:
    return None if value is None else int(value.seconds)


def _encoded(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, tuple):
        return [_encoded(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encoded(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _encoded(asdict(value))
    return str(value) if value.__class__.__name__ == "UUID" else value


def _content_hash(value) -> str:
    raw = json.dumps(_encoded(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _load(path: Path):
    return migrate(import_mspdi(str(path)))[0]


def _calculate(schedule):
    start = schedule.project.start
    if start is None:
        raise ValueError("controlled baseline has no project start")
    plan = build_plan(schedule, (start - timedelta(days=90), start + timedelta(days=365)))
    forward = forward_pass(
        plan.network,
        snap_milestones=plan.snap_milestones,
        progress_policy=plan.progress_policy,
    )
    backward = backward_pass(
        plan.network,
        forward,
        snap_milestones=plan.snap_milestones,
        progress_policy=plan.progress_policy,
    )
    floats = float_analysis(
        plan.network,
        forward,
        backward,
        threshold=plan.critical_float_threshold,
    )
    early, late, slack = forward.by_uid(), backward.by_uid(), floats.by_uid()
    result = {
        uid: (
            plan.to_datetime(early[uid].early_start),
            plan.to_datetime(early[uid].early_finish),
            plan.to_datetime(early[uid].early_start),
            plan.to_datetime(early[uid].early_finish),
            plan.to_datetime(late[uid].late_start),
            plan.to_datetime(late[uid].late_finish),
            slack[uid].total_float,
            slack[uid].free_float,
            slack[uid].critical,
        )
        for uid in plan.network.activity_by_uid()
    }
    return plan, forward, result


def _activities(schedule) -> dict[str, object]:
    return unique_rows((_source_uid(row), row) for row in schedule.activities)


def _observed(rows: dict[str, object]) -> dict[str, tuple[object, ...]]:
    return {
        source: (
            row.source_observations.start,
            row.source_observations.finish,
            row.source_observations.early_start,
            row.source_observations.early_finish,
            row.source_observations.late_start,
            row.source_observations.late_finish,
            row.source_observations.total_float_seconds,
            row.source_observations.free_float_seconds,
            row.source_observations.critical,
        )
        for source, row in rows.items()
    }


def _engine(schedule, result) -> dict[str, tuple[object, ...]]:
    return {
        _source_uid(row): result[row.uid]
        for row in schedule.activities
        if row.uid in result
    }


def _excluded(plan, schedule) -> dict[str, str]:
    """The coded activity identities omitted from the scheduled result."""

    by_uid = {row.uid: _source_uid(row) for row in schedule.activities}
    exclusions: dict[str, str] = {}
    for row in plan.excluded:
        if row.kind != "activity":
            continue
        source = by_uid[row.uid]
        if source in exclusions:
            raise ValueError(f"duplicate controlled-native exclusion: {source}")
        exclusions[source] = row.code
    return exclusions


def _relationship_signature(schedule) -> tuple[tuple[object, ...], ...]:
    activities = {_source_uid(row): row.uid for row in schedule.activities}
    by_uid = {uid: source for source, uid in activities.items()}
    return tuple(
        sorted(
            (
                by_uid[row.predecessor_uid],
                by_uid[row.successor_uid],
                row.type.value,
                _duration_seconds(row.lag),
                None if row.lag is None else row.lag.elapsed,
                row.lag_calendar.value,
            )
            for row in schedule.relationships
        )
    )


def _project_signature(schedule) -> tuple[object, ...]:
    calendars = {row.uid: _source_uid(row) for row in schedule.calendars}
    row = schedule.project
    return (
        row.start,
        row.status_date,
        row.must_finish_by,
        row.schedule_direction,
        row.progress_policy,
        row.lag_calendar_policy,
        row.milestone_snap_policy,
        calendars.get(row.default_calendar_uid),
        row.critical_float_threshold_seconds,
        row.minutes_per_day,
        row.minutes_per_week,
        row.days_per_month,
        row.timezone,
    )


def _calendar_fingerprint(schedule) -> str:
    rows = unique_rows((_source_uid(row), row) for row in schedule.calendars)
    by_uid = {row.uid: source for source, row in rows.items()}
    normalized = {
        source: (
            row.name,
            row.type,
            by_uid.get(row.base_uid),
            row.week,
            row.exceptions,
            row.hours_per_day_seconds,
            row.hours_per_week_seconds,
            row.hours_per_month_seconds,
        )
        for source, row in rows.items()
    }
    return _content_hash(normalized)


def _resource_fingerprint(schedule) -> str:
    rows = unique_rows((_source_uid(row), row) for row in schedule.resources)
    calendars = {row.uid: _source_uid(row) for row in schedule.calendars}
    normalized = {
        source: (
            row.name,
            row.code,
            row.type,
            row.scheduling_class,
            row.max_units_permille,
            calendars.get(row.calendar_uid),
            row.group,
            row.inactive,
            row.is_role,
        )
        for source, row in rows.items()
    }
    return _content_hash(normalized)


def _wbs_fingerprint(schedule) -> str:
    rows = unique_rows((_source_uid(row), row) for row in schedule.wbs_nodes)
    by_uid = {row.uid: source for source, row in rows.items()}
    return _content_hash(
        {
            source: (row.code, row.name, by_uid.get(row.parent_uid), row.seq, row.level)
            for source, row in rows.items()
        }
    )


def _constraint_value(value):
    if value is None:
        return None
    return (value.type, value.date, value.hard)


def _activity_static(schedule, row, *, selected: bool) -> tuple[object, ...]:
    wbs = {item.uid: _source_uid(item) for item in schedule.wbs_nodes}
    calendars = {item.uid: _source_uid(item) for item in schedule.calendars}
    return (
        wbs.get(row.wbs_uid),
        row.code,
        row.kind,
        row.seq,
        row.active,
        row.manual,
        row.duration_type,
        row.effort_driven,
        None if selected else row.planned_duration,
        None if selected else row.planned_work,
        calendars.get(row.calendar_uid),
        _constraint_value(row.primary_constraint),
        _constraint_value(row.secondary_constraint),
        row.deadline,
        row.priority,
        row.levelling_delay_seconds,
        tuple((item.code_type_uid, item.code_value_uid) for item in row.codes),
    )


@unittest.skipUnless(
    _PRESENT,
    "the controlled native BOILER pair is absent; set STO_REQUIRE_CONTROLLED_NATIVE=1",
)
class ControlledNativeProgressBoilerTests(unittest.TestCase):
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

    def test_identity_relationships_and_exact_control_are_preserved(self):
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
        self.assertEqual(_duration_seconds(before.remaining_duration), 7_200)
        self.assertEqual(_duration_seconds(native.remaining_duration), 3_600)

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
                    new.remaining_duration,
                    new.percent_complete,
                    new.planned_duration,
                    new.planned_work,
                    new.active,
                    new.manual,
                ),
                source,
            )

    def test_project_derived_progress_values_reconcile(self):
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

    def test_corrected_engine_reproduces_the_measured_started_work_rule(self):
        selected = self.before_rows[TARGET_SOURCE_UID]
        controlled_late = self.control_plan.to_datetime(
            backward_pass(
                self.control_plan.network,
                self.control_forward,
                snap_milestones=self.control_plan.snap_milestones,
                progress_policy=self.control_plan.progress_policy,
            ).by_uid()[selected.uid].late_start
        )
        self.assertEqual(controlled_late, TARGET_ACTUAL_START)
        self.assertEqual(
            controlled_late,
            self.native_rows[TARGET_SOURCE_UID].source_observations.late_start,
        )

    def test_complete_contract_has_three_unexplained_fields(self):
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
                BASELINE_MISMATCH: 419,
                ENGINE_NATIVE_AGREEMENT: 128,
                EXPLICIT_EXCLUSION: 81,
                UNCHANGED: 3_509,
                UNEXPLAINED: 3,
            },
        )
        self.assertEqual(
            summary.unexplained,
            (
                ("5", "late_start"),
                ("5", "late_finish"),
                ("5", "total_float"),
            ),
        )
        self.assertEqual(len(summary.baseline_mismatches), 419)
        self.assertEqual(
            Counter(field for _, field in summary.baseline_mismatches),
            {
                "start": 62,
                "finish": 67,
                "early_start": 62,
                "early_finish": 67,
                "late_start": 41,
                "late_finish": 32,
                "total_float": 70,
                "free_float": 16,
                "critical": 2,
            },
        )

    def test_assignment_schedule_outputs_move_without_input_corruption(self):
        before_assignments = unique_rows(
            (_source_uid(row), row) for row in self.before.assignments
        )
        native_assignments = unique_rows(
            (_source_uid(row), row) for row in self.native.assignments
        )
        self.assertEqual(set(before_assignments), set(native_assignments))
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
            selected = old.activity_uid == self.before_rows[TARGET_SOURCE_UID].uid
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
            if not selected:
                self.assertEqual(old.work, new.work, source)
                self.assertEqual(
                    old.percent_work_complete_permille,
                    new.percent_work_complete_permille,
                    source,
                )
            changed_spans += (old.start, old.finish) != (new.start, new.finish)
        self.assertEqual(changed_spans, 7)

    def test_sto_changed_cohort_is_measured_after_the_correction(self):
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
        self.assertEqual(len(changed), 31)
        self.assertEqual(len(moved_downstream), 6)
        dispositions = Counter(
            "EXCLUDED_CODED"
            if row.uid not in self.control_result
            else "ASSUMED_LABELLED"
            if row.uid in {
                item.uid for item in self.control_plan.assumed if item.kind == "activity"
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
