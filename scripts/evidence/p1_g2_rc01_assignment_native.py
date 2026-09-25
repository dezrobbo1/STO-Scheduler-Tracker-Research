#!/usr/bin/env python3
"""Analyze the predeclared RC01 assignment-envelope Microsoft Project return.

This is evidence tooling only.  It validates every experiment-defining input
before reading the native output fields and can authorize only a later,
diagnostic-only BOILER counterfactual.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Mapping
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence import p1_g2_rc01_assignment_native_generate as generate

NS = {"p": generate.URI}
SCHEMA = "sto-p1-g2-rc01-assignment-envelope-native-v1"
DATE_FIELDS = ("Start", "Finish", "EarlyStart", "EarlyFinish")
NATIVE_BUILD = re.compile(r"^16\.0\.\d+\.\d+$")


class NativeEvidenceError(ValueError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _text(parent: ET.Element, field: str) -> str | None:
    return parent.findtext(f"p:{field}", default=None, namespaces=NS)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeEvidenceError(message)


def _datetime(value: str | None, where: str) -> datetime:
    try:
        result = datetime.fromisoformat(value or "")
    except ValueError as error:
        raise NativeEvidenceError(f"missing or invalid native date: {where}") from error
    if result.tzinfo is not None:
        raise NativeEvidenceError(f"timezone-bearing native date is outside contract: {where}")
    return result


def _decimal(value: str | None, where: str) -> Decimal:
    try:
        return Decimal(value or "")
    except InvalidOperation as error:
        raise NativeEvidenceError(f"missing or invalid numeric input: {where}") from error


def _named(container: ET.Element | None, kind: str) -> dict[str, ET.Element]:
    _require(container is not None, f"native return is missing {kind} container")
    rows: dict[str, ET.Element] = {}
    for row in list(container):
        name = _text(row, "Name")
        if name:
            _require(name not in rows, f"native return duplicates {kind} name {name}")
            rows[name] = row
    return rows


def _calendar_signature(row: ET.Element) -> tuple[tuple[int, bool, tuple[tuple[str, str], ...]], ...]:
    result: list[tuple[int, bool, tuple[tuple[str, str], ...]]] = []
    for weekday in row.findall("p:WeekDays/p:WeekDay", NS):
        day_text = _text(weekday, "DayType")
        _require(day_text is not None and day_text.isdigit(), "calendar has invalid weekday identity")
        intervals = tuple(
            (_text(item, "FromTime") or "", _text(item, "ToTime") or "")
            for item in weekday.findall("p:WorkingTimes/p:WorkingTime", NS)
        )
        result.append((int(day_text), _text(weekday, "DayWorking") == "1", intervals))
    return tuple(result)


def _expected_calendar_signature(intervals: tuple[tuple[str, str], ...]):
    return tuple(
        (day, 2 <= day <= 6, intervals if 2 <= day <= 6 else ())
        for day in range(1, 8)
    )


def parse_and_validate(payload: bytes) -> dict[str, object]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise NativeEvidenceError(f"native return is not valid MSPDI XML: {error}") from error
    _require(root.tag == generate.q("Project"), "native return is not an MSPDI Project")

    expected_project = {
        "Name": generate.PROJECT_NAME,
        "GUID": generate.PROJECT_GUID,
        "ScheduleFromStart": "1",
        "StartDate": generate.PROJECT_START,
        "CalendarUID": "1",
        "DefaultStartTime": "08:00:00",
        "DefaultFinishTime": "17:00:00",
        "MinutesPerDay": "480",
        "MinutesPerWeek": "2400",
        "DaysPerMonth": "20",
        "DefaultTaskType": "0",
        "NewTasksEffortDriven": "0",
        "NewTasksEstimated": "0",
        "NewTasksAreManual": "0",
    }
    for field, expected in expected_project.items():
        _require(_text(root, field) == expected, f"project input changed: {field}")

    calendars = _named(root.find("p:Calendars", NS), "calendar")
    _require(
        set(calendars) == {str(spec["name"]) for spec in generate.CALENDARS.values()},
        "calendar identity set changed",
    )
    for uid, spec in generate.CALENDARS.items():
        name = str(spec["name"])
        _require(name in calendars, f"calendar identity changed or missing: {name}")
        row = calendars[name]
        expected = {
            "UID": str(uid),
            "GUID": str(spec["guid"]),
            "IsBaseCalendar": "1" if uid == 1 else "0",
            "BaseCalendarUID": str(spec["base"]),
        }
        for field, value in expected.items():
            _require(_text(row, field) == value, f"calendar input changed: {name}.{field}")
        _require(
            _calendar_signature(row) == _expected_calendar_signature(spec["intervals"]),
            f"calendar working intervals changed: {name}",
        )
        _require(
            not row.findall("p:Exceptions/p:Exception", NS),
            f"calendar exceptions changed: {name}",
        )

    task_rows = _named(root.find("p:Tasks", NS), "task")
    _require(
        set(task_rows) == {f"RC01-CASE-{case}" for case in generate.TASKS},
        "task identity set changed",
    )
    tasks: dict[str, dict[str, object]] = {}
    for case, spec in generate.TASKS.items():
        name = f"RC01-CASE-{case}"
        _require(name in task_rows, f"task identity changed or missing: {name}")
        row = task_rows[name]
        exact = {
            "UID": str(spec["uid"]),
            "GUID": str(spec["guid"]),
            "ID": str(spec["uid"]),
            "Active": "1",
            "Manual": "0",
            "Type": "0",
            "Duration": generate.TASK_DURATION,
            "DurationFormat": "7",
            "Work": str(spec["work"]),
            "EffortDriven": "0",
            "Estimated": "0",
            "Milestone": "0",
            "Summary": "0",
            "PercentComplete": "0",
            "PercentWorkComplete": "0",
            "ActualDuration": "PT0H0M0S",
            "ActualWork": "PT0H0M0S",
            "RemainingDuration": generate.TASK_DURATION,
            "RemainingWork": str(spec["work"]),
            "ConstraintType": "0",
            "LevelAssignments": "0",
            "LevelingCanSplit": "0",
            "LevelingDelay": "0",
            "IgnoreResourceCalendar": "0",
        }
        labels = {
            "GUID": "task identity",
            "UID": "task identity",
            "ID": "task identity",
            "Type": "task type",
            "EffortDriven": "effort driven",
            "IgnoreResourceCalendar": "ignore resource calendar",
            "Duration": "duration",
            "Start": "start",
        }
        for field, expected in exact.items():
            _require(
                _text(row, field) == expected,
                f"{labels.get(field, 'task input')} changed: {name}.{field}",
            )
        _require(_text(row, "CalendarUID") is None, f"task calendar changed: {name}")
        _require(not row.findall("p:PredecessorLink", NS), f"topology changed: {name}")
        start = _datetime(_text(row, "Start"), f"{name}.Start")
        _require(start == datetime.fromisoformat(generate.PROJECT_START), f"start changed: {name}")
        date_keys = {
            "Start": "start",
            "Finish": "finish",
            "EarlyStart": "early_start",
            "EarlyFinish": "early_finish",
        }
        dates = {
            date_keys[field]: _datetime(
                _text(row, field), f"{name}.{field}"
            ).isoformat()
            for field in DATE_FIELDS
        }
        tasks[case] = {
            "uid": int(spec["uid"]),
            "type": _text(row, "Type"),
            "effort_driven": _text(row, "EffortDriven"),
            "ignore_resource_calendar": _text(row, "IgnoreResourceCalendar"),
            "duration": _text(row, "Duration"),
            **dates,
        }

    resource_rows = _named(root.find("p:Resources", NS), "resource")
    _require(
        set(resource_rows) == {str(spec["name"]) for spec in generate.RESOURCES.values()},
        "resource identity set changed",
    )
    resources: dict[int, dict[str, object]] = {}
    for uid, spec in generate.RESOURCES.items():
        name = str(spec["name"])
        _require(name in resource_rows, f"resource identity changed or missing: {name}")
        row = resource_rows[name]
        exact = {
            "UID": str(uid),
            "GUID": str(spec["guid"]),
            "ID": str(uid),
            "Type": "1",
            "MaxUnits": Decimal("1"),
            "CanLevel": "0",
            "CalendarUID": str(spec["calendar"]),
            "IsInactive": "0",
        }
        for field, expected in exact.items():
            if field == "MaxUnits":
                actual: object = _decimal(_text(row, field), f"{name}.{field}")
            else:
                actual = _text(row, field)
            label = "resource calendar" if field == "CalendarUID" else "resource identity" if field in {"UID", "GUID", "ID"} else "resource input"
            _require(actual == expected, f"{label} changed: {name}.{field}")
        resources[uid] = {"name": name, "calendar_uid": int(spec["calendar"])}

    assignments_element = root.find("p:Assignments", NS)
    _require(assignments_element is not None, "native return is missing assignments")
    assignment_rows = list(assignments_element)
    order = [_text(row, "UID") for row in assignment_rows]
    expected_order = [str(uid) for uid in generate.ASSIGNMENT_ORDER]
    _require(order == expected_order, "assignment order changed")
    assignments: dict[int, dict[str, object]] = {}
    specs = {int(row["uid"]): row for row in generate.ASSIGNMENTS}
    for row in assignment_rows:
        uid_text = _text(row, "UID")
        _require(uid_text is not None and uid_text.isdigit(), "assignment identity is invalid")
        uid = int(uid_text)
        _require(uid in specs, f"assignment identity changed: {uid}")
        spec = specs[uid]
        exact_text = {
            "GUID": str(spec["guid"]),
            "TaskUID": str(generate.TASKS[spec["case"]]["uid"]),
            "ResourceUID": str(spec["resource"]),
            "Work": generate.ASSIGNMENT_WORK,
            "ActualWork": "PT0H0M0S",
            "RemainingWork": generate.ASSIGNMENT_WORK,
            "PercentWorkComplete": "0",
            "Delay": "0",
            "LevelingDelay": "0",
        }
        for field, expected in exact_text.items():
            label = (
                "assignment identity" if field in {"GUID", "TaskUID", "ResourceUID"}
                else "assignment work" if field in {"Work", "ActualWork", "RemainingWork"}
                else "assignment input"
            )
            _require(_text(row, field) == expected, f"{label} changed: {uid}.{field}")
        _require(
            _decimal(_text(row, "Units"), f"assignment {uid}.Units")
            == Decimal(generate.ASSIGNMENT_UNITS),
            f"assignment units changed: {uid}.Units",
        )
        assignments[uid] = {
            "uid": uid,
            "case": str(spec["case"]),
            "role": str(spec["role"]),
            "resource_uid": int(spec["resource"]),
            "work": _text(row, "Work"),
            "units": str(_decimal(_text(row, "Units"), f"assignment {uid}.Units")),
            "start": _datetime(_text(row, "Start"), f"assignment {uid}.Start").isoformat(),
            "finish": _datetime(_text(row, "Finish"), f"assignment {uid}.Finish").isoformat(),
        }

    return {
        "project": {
            "name": _text(root, "Name"),
            "guid": _text(root, "GUID"),
            "build_number": _text(root, "BuildNumber"),
            "start": _text(root, "StartDate"),
            "calendar_uid": _text(root, "CalendarUID"),
        },
        "calendars": {
            uid: {
                "name": spec["name"],
                "intervals": [list(row) for row in spec["intervals"]],
            }
            for uid, spec in generate.CALENDARS.items()
        },
        "resources": resources,
        "tasks": tasks,
        "assignments": assignments,
        "assignment_order": [int(value) for value in order if value is not None],
    }


def _dt(value: object) -> datetime:
    if not isinstance(value, str):
        raise NativeEvidenceError("classification observation is missing a date")
    return _datetime(value, "classification observation")


def _case_observations(parsed: dict[str, object]) -> dict[str, object]:
    tasks = parsed["tasks"]
    assignments = parsed["assignments"]
    observations: dict[str, object] = {}
    for case in "ABCD":
        case_assignments = [
            row for row in assignments.values() if row["case"] == case
        ]
        task = tasks[case]
        observations[case] = {
            "task": {
                "start": task["start"],
                "finish": task["finish"],
                "early_start": task["early_start"],
                "early_finish": task["early_finish"],
                "duration": task["duration"],
            },
            "assignments": {
                row["role"]: {
                    "uid": row["uid"],
                    "resource_uid": row["resource_uid"],
                    "start": row["start"],
                    "finish": row["finish"],
                    "work": row["work"],
                    "units": row["units"],
                }
                for row in case_assignments
            },
            "union_prediction": {
                "start": generate.PROJECT_START,
                "finish": "2026-10-12T12:00:00",
            },
        }
    return observations


def classify(observations: dict[str, object]) -> dict[str, object]:
    def task(case: str, field: str) -> datetime:
        return _dt(observations[case]["task"][field])

    def assignment(case: str, role: str, field: str) -> datetime:
        return _dt(observations[case]["assignments"][role][field])

    assignment_calendar_compatible: dict[str, bool] = {}
    for case in "ABCD":
        for role, row in observations[case]["assignments"].items():
            expected = (
                (datetime(2026, 10, 12, 13), datetime(2026, 10, 12, 17))
                if role == "PM"
                else (datetime(2026, 10, 12, 8), datetime(2026, 10, 12, 12))
            )
            assignment_calendar_compatible[f"{case}.{role}"] = (
                _dt(row["start"]) == expected[0]
                and _dt(row["finish"]) == expected[1]
                and row["work"] == generate.ASSIGNMENT_WORK
                and Decimal(str(row["units"])) == Decimal(generate.ASSIGNMENT_UNITS)
            )

    envelope_checks: dict[str, bool] = {}
    for case in "ABC":
        spans = observations[case]["assignments"].values()
        envelope_checks[case] = (
            task(case, "start") == min(_dt(row["start"]) for row in spans)
            and task(case, "finish") == max(_dt(row["finish"]) for row in spans)
            and task(case, "early_start") == task(case, "start")
            and task(case, "early_finish") == task(case, "finish")
        )

    order_twin = (
        task("A", "start") == task("B", "start")
        and task("A", "finish") == task("B", "finish")
        and all(
            assignment("A", role, field) == assignment("B", role, field)
            for role in ("AM", "PM")
            for field in ("start", "finish")
        )
    )
    overlap_control = (
        envelope_checks["C"]
        and task("C", "start") == datetime(2026, 10, 12, 8)
        and task("C", "finish") == datetime(2026, 10, 12, 12)
    )
    single = observations["D"]["assignments"]["AM"]
    single_control = (
        task("D", "start") == _dt(single["start"])
        and task("D", "finish") == _dt(single["finish"])
        and task("D", "start") == datetime(2026, 10, 12, 8)
        and task("D", "finish") == datetime(2026, 10, 12, 12)
    )
    separated_differs_from_union = all(
        task(case, "finish")
        != _dt(observations[case]["union_prediction"]["finish"])
        for case in "AB"
    )
    controls_valid = (
        overlap_control
        and single_control
        and all(assignment_calendar_compatible.values())
    )
    predicates = {
        "all_assignment_spans_match_their_resource_calendars": all(
            assignment_calendar_compatible.values()
        ),
        "two_assignment_tasks_equal_assignment_envelopes": all(
            envelope_checks.values()
        ),
        "assignment_order_twin_is_identical": order_twin,
        "overlap_control_is_valid": overlap_control,
        "single_resource_control_is_valid": single_control,
        "separated_cases_differ_from_union_prediction": separated_differs_from_union,
    }
    if all(predicates.values()):
        verdict = "ASSIGNMENT_ENVELOPE_SUPPORTED"
    elif controls_valid and order_twin and not all(envelope_checks[case] for case in "AB"):
        verdict = "ASSIGNMENT_ENVELOPE_REJECTED"
    else:
        verdict = "NATIVE_RESULT_INCONCLUSIVE"
    return {
        "verdict": verdict,
        "predicates": predicates,
        "controls_valid": controls_valid,
        "assignment_calendar_compatibility": assignment_calendar_compatible,
        "envelope_checks": envelope_checks,
        "observations": observations,
    }


def analyze(payload: bytes) -> dict[str, object]:
    parsed = parse_and_validate(payload)
    observations = _case_observations(parsed)
    generated = (
        len(payload) == generate.INPUT_BYTES
        and _sha256(payload) == generate.INPUT_SHA256
    )
    build = parsed["project"]["build_number"]
    if generated or not isinstance(build, str) or NATIVE_BUILD.fullmatch(build) is None:
        classification = {
            "verdict": "NOT_RUN_UNRECALCULATED_INPUT",
            "predicates": {},
            "controls_valid": False,
            "observations": observations,
        }
    else:
        classification = classify(observations)
    passed = classification["verdict"] == "ASSIGNMENT_ENVELOPE_SUPPORTED"
    return {
        "schema": SCHEMA,
        "experiment_id": generate.EXPERIMENT_ID,
        "input_identity": {
            "path": "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1.xml",
            "bytes": generate.INPUT_BYTES,
            "sha256": generate.INPUT_SHA256,
        },
        "native_return": {"bytes": len(payload), "sha256": _sha256(payload)},
        "project": parsed["project"],
        "predeclared_contract": {
            "fields_read": {
                "project": ["BuildNumber", "Name", "GUID", "StartDate", "CalendarUID"],
                "task_inputs": [
                    "UID", "GUID", "ID", "Type", "EffortDriven",
                    "IgnoreResourceCalendar", "Duration", "Work", "Start",
                    "CalendarUID", "ConstraintType", "Manual", "PercentComplete",
                    "LevelAssignments", "LevelingCanSplit", "LevelingDelay",
                ],
                "task_outputs": list(DATE_FIELDS),
                "resource_inputs": ["UID", "GUID", "CalendarUID", "MaxUnits", "CanLevel"],
                "assignment_inputs": [
                    "UID", "GUID", "TaskUID", "ResourceUID", "Work", "Units",
                    "ActualWork", "RemainingWork", "Delay", "LevelingDelay",
                ],
                "assignment_outputs": ["Start", "Finish"],
                "calendar_inputs": ["UID", "GUID", "BaseCalendarUID", "WeekDays.WorkingTimes"],
            },
            "controls": {
                "C": "two distinct but fully overlapping resource calendars",
                "D": "single-resource supported-rule control",
            },
            "acceptance": "all six predicates in classification.predicates are true",
            "support": "ASSIGNMENT_ENVELOPE_SUPPORTED",
            "rejection": (
                "valid controls and stable order twin, but one or both separated tasks "
                "do not equal their assignment envelope"
            ),
            "inconclusive": "any invalid control, order effect or mixed observation",
            "stopping_rule": (
                "support authorizes only a later diagnostic BOILER counterfactual; "
                "rejection or inconclusive stops RC01 without a production change"
            ),
        },
        "classification": classification,
        "decision": {
            "native_experiment_passed": passed,
            "boiler_counterfactual_authorized": passed,
            "production_correction_authorized": False,
        },
    }


def serialize(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def refuse_output_alias(output: Path, sources: Mapping[str, Path]) -> None:
    output_resolved = output.resolve(strict=False)
    for role, source in sources.items():
        same_path = output_resolved == source.resolve(strict=False)
        same_object = False
        if output.exists() or output.is_symlink():
            try:
                same_object = output.samefile(source)
            except FileNotFoundError:
                same_object = False
            except OSError as error:
                raise NativeEvidenceError(
                    f"cannot establish whether output is separate from {role}"
                ) from error
        if same_path or same_object:
            raise NativeEvidenceError(f"output must be separate from {role}")


def write_output_safely(
    output: Path,
    payload: str,
    sources: Mapping[str, Path],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    refuse_output_alias(output, sources)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        refuse_output_alias(output, sources)
        os.replace(temporary, output)
        temporary = None
        directory_descriptor = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as error:
        raise NativeEvidenceError(f"cannot safely publish native evidence: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("native_return", type=Path)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--check", type=Path)
    args = parser.parse_args()
    sources = {"native return": args.native_return}
    if args.output:
        refuse_output_alias(args.output, sources)
    if args.check:
        refuse_output_alias(args.check, sources)
    before = args.native_return.read_bytes()
    payload = serialize(analyze(before))
    if args.native_return.read_bytes() != before:
        raise NativeEvidenceError("native return changed while it was being analyzed")
    if args.check:
        if args.check.read_bytes() != payload.encode("utf-8"):
            raise SystemExit("candidate evidence does not match this native return")
    elif args.output:
        write_output_safely(args.output, payload, sources)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
