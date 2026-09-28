#!/usr/bin/env python3
"""Predeclared fail-closed analyzer for genuine networked V3 Project returns."""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence import p1_g2_rc01_assignment_native_v2 as v2
from scripts.evidence import p1_g2_rc01_networked_v3_generate as matrix
from scripts.evidence import p1_g2_rc01_networked_v3_oracle as oracle

NS = {"p": matrix.URI}
SCHEMA = "sto-p1-g2-rc01-networked-assignment-envelope-native-v3"
LINEAGE = {
    "docs/evidence/p1-g2-post-rc02-review-2026-09-25.json": "9a3ef68637b6e213188400f05fdca9bd216eebfbafa100f10f817623f5b8f3d3",
    "docs/evidence/p1-g2-rc01-native-v2-valid-return-2026-09-28.json": "71702adb09f08014c8ce14bed7651162bff65787f8d4d4945bb2383710ca6a6c",
    "docs/evidence/p1-g2-rc01-boiler-counterfactual-reviewed-v3-2026-09-28.json": matrix.AUDIT_SHA256,
    "docs/evidence/p1-g2-rc01-boiler-counterfactual-impact-2026-09-28.json": "ec2adf6b5f07b293fb72865963fc34d97870256385e160be339b70b69b029b96",
}
TASK_OUTPUTS = {"Start", "Finish", "Duration", "RemainingDuration", "EarlyStart",
                "EarlyFinish", "LateStart", "LateFinish", "TotalSlack", "FreeSlack", "Critical"}
ASSIGNMENT_OUTPUTS = {"Start", "Finish"}
RESOURCE_OUTPUTS = {"PeakUnits", "OverAllocated"}
PROJECT_OUTPUTS = {"FinishDate", "BuildNumber", "GUID"}
NativeEvidenceError = v2.NativeEvidenceError


def _text(row: ET.Element, key: str) -> str | None:
    return row.findtext(f"p:{key}", namespaces=NS)


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise NativeEvidenceError(message)


def _rows(parent: ET.Element, section: str, permitted_extra: set[int] = frozenset()) -> dict[int, ET.Element]:
    collection = parent.find(f"p:{section}", NS)
    _require(collection is not None, f"missing {section}")
    result = {}
    for row in collection:
        _require(row.tag == matrix.q(section[:-1]), f"unexpected {section} row")
        uid = _text(row, "UID")
        _require(uid is not None and uid.isdigit(), f"invalid {section} UID")
        _require(int(uid) not in result, f"duplicate {section} UID")
        result[int(uid)] = row
    return result


def _check_row(observed: ET.Element, expected: ET.Element, outputs: set[str],
               additions: set[str], label: str) -> None:
    links = expected.findall("p:PredecessorLink", NS)
    if links:
        returned_links = observed.findall("p:PredecessorLink", NS)
        _require(len(returned_links) == len(links) and
                 all(ET.tostring(left) == ET.tostring(right)
                     for left, right in zip(returned_links, links)),
                 f"relationship/topology changed: {label}")
    v2._validate_save_delta(observed, expected, outputs | {"PredecessorLink"}, additions, label)
    repeating = {matrix.q("PredecessorLink"), matrix.q("TimephasedData")}
    _require(len({child.tag for child in observed if child.tag not in repeating})
             == len([child for child in observed if child.tag not in repeating]),
             f"duplicate field at {label}")


def _date(row: ET.Element, field: str, label: str) -> datetime:
    return v2._datetime(_text(row, field), f"{label}.{field}")


def _working_duration(start: datetime, finish: datetime) -> str:
    minutes = oracle.signed_project_minutes(start, finish)
    _require(minutes >= 0, "negative task working duration")
    return f"PT{minutes // 60}H{minutes % 60}M0S"


def _expected_calendar(row: ET.Element, calendar_uid: int) -> bool:
    observed = v2._calendar_signature(row)
    expected = tuple((day, calendar_uid != 1 or 2 <= day <= 6,
                      matrix.INTERVALS[matrix.CALENDARS[calendar_uid][1]]
                      if calendar_uid != 1 or 2 <= day <= 6 else ())
                     for day in range(1, 8))
    # Project works weekdays only; all seven days work on resource calendars.
    # V2's omitted NONworking weekend normalization does not apply to resources.
    return observed == expected


def verified_lineage() -> dict:
    for path, digest in LINEAGE.items():
        _require(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest,
                 f"historical evidence identity changed: {path}")
    _require(hashlib.sha256((ROOT / matrix.FIXTURE).read_bytes()).hexdigest() ==
             matrix.INPUT_SHA256, "pinned V3 matrix identity changed")
    result = json.loads((ROOT / matrix.AUDIT).read_bytes())
    _require(result["before"]["slots"] == 147 and result["before"]["rc01"] == 144 and
             result["before"]["rc03"] == 3 and result["after"]["slots"] == 3 and
             result["after"]["rc01_remaining"] == 0 and result["after"]["rc03_remaining"] == 3 and
             result["movement"]["rc01_closed"] == 144 and
             not result["movement"]["new_keys"] and result["movement"]["other_worsened"] == 0 and
             not result["validator"]["violations"] and
             not result["decision"]["production_rc01_correction_authorized"],
             "merged BOILER counterfactual movement/decision changed")
    return {"sha256_by_path": LINEAGE, "boiler_source_identity": result["source"],
            "before_slots": 147, "rc01_closed": 144, "rc03_after": 3}


def _native_inputs(payload: bytes) -> dict:
    try:
        result = ET.fromstring(payload)
    except ET.ParseError as error:
        raise NativeEvidenceError("invalid MSPDI XML") from error
    _require(result.tag == matrix.q("Project"), "not an MSPDI Project")
    fixed = ET.fromstring(matrix.build_fixture())
    _check_row(result, fixed, PROJECT_OUTPUTS | {"AutoLink", "Autolink",
                 "Calendars", "Tasks", "Resources", "Assignments"},
               v2.PROJECT_METADATA | v2.PROJECT_SAVE_CONTAINERS
               | set(v2.PROJECT_NORMALIZED_OPTIONS) | {"Autolink"}, "project")
    _require(_text(result, "Name") == matrix.PROJECT_NAME and
             _text(result, "Title") == matrix.EXPERIMENT_ID,
             "project identity changed")
    _require(v2.GUID.fullmatch(_text(result, "GUID") or "") is not None,
             "project GUID normalization invalid")
    _require(_text(result, "AutoLink") in (None, "0") and
             _text(result, "Autolink") in (None, "0") and
             (_text(result, "AutoLink") is not None or _text(result, "Autolink") is not None),
             "project AutoLink changed")
    for field, value in v2.PROJECT_NORMALIZED_OPTIONS.items():
        _require(_text(result, field) in (None, value), f"project option changed: {field}")
    for field, value in v2.PROJECT_METADATA_VALUES.items():
        _require(_text(result, field) in (None, value), f"unknown save value: {field}")
    for field in ("CreationDate", "CurrentDate", "LastSaved"):
        if _text(result, field) is not None:
            _date(result, field, "project")
    for field in v2.PROJECT_EMPTY_CONTAINERS:
        container = result.find(f"p:{field}", NS)
        _require(container is None or len(container) == 0, f"unexpected {field} contents")
    expected_calendars = _rows(fixed, "Calendars")
    calendars = _rows(result, "Calendars")
    if 5 in calendars:
        extra = calendars.pop(5)
        for field, value in {"UID": "5", "Name": "Standard", "IsBaseCalendar": "1",
                             "BaseCalendarUID": "0"}.items():
            _require(_text(extra, field) == value,
                     f"unexpected inert native default calendar: {field}")
        _require(not any(_text(item, "CalendarUID") == "5" for item in
                         result.findall("p:Resources/p:Resource", NS) +
                         result.findall("p:Tasks/p:Task", NS)),
                 "native default calendar participates in scheduling")
    _require(set(calendars) == set(expected_calendars), "calendar UID set changed")
    for uid, expected in expected_calendars.items():
        actual = calendars[uid]
        _check_row(actual, expected, {"Name", "WeekDays"} if uid != 1 else set(),
                   set(), f"calendar {uid}")
        _require(_text(actual, "Name") in
                 ({matrix.CALENDARS[uid][0], "Unassigned"} if uid != 1 else
                  {matrix.CALENDARS[uid][0]}), f"calendar name changed: {uid}")
        _require(_expected_calendar(actual, uid), f"working intervals changed: {uid}")
        _require(not actual.findall("p:Exceptions/p:Exception", NS),
                 f"calendar exception changed: {uid}")
    expected_tasks = _rows(fixed, "Tasks")
    tasks = _rows(result, "Tasks")
    # V2 witnessed the inert native summary task UID 0. It must have no links,
    # assignments or changed flags; task UID/name/GUID of real rows remain exact.
    if 0 in tasks:
        summary = tasks.pop(0)
        _require(_text(summary, "Summary") == "1" and
                 not summary.findall("p:PredecessorLink", NS) and
                 _text(summary, "Name") in (matrix.EXPERIMENT_ID, matrix.PROJECT_NAME) and
                 _text(summary, "Manual") in (None, "0") and
                 _text(summary, "Active") in (None, "1"), "native summary changed")
        for field, value in {"Type": "1", "CalendarUID": "-1", "ConstraintType": "0",
                             "PercentComplete": "0", "PercentWorkComplete": "0",
                             "ActualWork": matrix.ZERO, "LevelingDelay": "0"}.items():
            _require(_text(summary, field) == value, f"summary input changed: {field}")
        v2._guard_extra(summary, next(iter(expected_tasks.values())),
                        v2.TASK_SAVE_FIELDS | TASK_OUTPUTS | {"CalendarUID"}, "native summary")
    _require(set(tasks) == set(expected_tasks), "task UID set changed")
    task_specs, edges, assignment_specs = matrix.graph()
    observed: dict[str, dict] = {}
    for name, spec in task_specs.items():
        uid = spec["uid"]
        task = tasks[uid]
        _check_row(task, expected_tasks[uid], TASK_OUTPUTS | {"LevelingDelayFormat", "CalendarUID"},
                   v2.TASK_SAVE_FIELDS | {"CalendarUID", "LevelingDelayFormat"}, f"task {name}")
        _require(_text(task, "Name") == f"V3-{name}" and
                 _text(task, "GUID") == matrix.guid("task", name), f"task identity changed: {name}")
        _require(_text(task, "CalendarUID") in (None, "-1"), f"task calendar changed: {name}")
        _require(_text(task, "LevelingDelayFormat") in ("7", "8"),
                 f"task levelling format changed: {name}")
        _require(_text(task, "ActualWork") == matrix.ZERO and
                 _text(task, "PercentComplete") == "0" and
                 _text(task, "PercentWorkComplete") == "0", f"task progressed: {name}")
        _require(_text(task, "ManualStart") in (None, _text(task, "Start")) and
                 _text(task, "ManualFinish") in (None, _text(task, "Finish")) and
                 _text(task, "ManualDuration") in (None, _text(task, "Duration")),
                 f"unexplained manual fields: {name}")
        v2._check_witnessed_save_inputs(task, f"task {name}", {
            "ActualOvertimeWork": matrix.ZERO, "OvertimeWork": matrix.ZERO,
            "RemainingOvertimeWork": matrix.ZERO, "ExternalTask": "0",
            "IsSubproject": "0", "IsSubprojectReadOnly": "0", "ResumeValid": "0"})
        if not spec["predecessors"]:
            _require(_date(task, "Start", name) == datetime.fromisoformat(matrix.PROJECT_START),
                     f"unbounded task start changed: {name}")
        fields = {field: _date(task, field, name) for field in
                  ("Start", "Finish", "EarlyStart", "EarlyFinish", "LateStart", "LateFinish")}
        fields["Duration"] = _text(task, "Duration")
        fields["RemainingDuration"] = _text(task, "RemainingDuration")
        for field in ("TotalSlack", "FreeSlack"):
            raw = _text(task, field)
            _require(raw is not None and re.fullmatch(r"-?[0-9]+", raw) is not None,
                     f"invalid {name}.{field}")
            fields[field] = int(raw)
        critical = _text(task, "Critical")
        _require(critical in ("0", "1"), f"invalid criticality: {name}")
        fields["Critical"] = critical == "1"
        observed[name] = fields
    resources = _rows(result, "Resources")
    expected_resources = _rows(fixed, "Resources")
    if 0 in resources:
        null = resources.pop(0)
        _require(_text(null, "ID") == "0" and _text(null, "CanLevel") == "1" and
                 _text(null, "CalendarUID") is not None, "native null resource changed")
    _require(set(resources) == set(expected_resources), "resource UID set changed")
    for uid, expected in expected_resources.items():
        resource = resources[uid]
        _check_row(resource, expected, RESOURCE_OUTPUTS | {"GUID", "MaxUnits"},
                   v2.RESOURCE_SAVE_FIELDS, f"resource {uid}")
        spec = assignment_specs[uid]
        _require(_text(resource, "GUID") in (matrix.guid("resource", uid),
                 matrix.guid("calendar", spec["calendar"])),
                 f"resource GUID changed: {uid}")
        _require(_text(resource, "CalendarUID") == str(spec["calendar"]) and
                 _text(resource, "CanLevel") == "0" and
                 v2._decimal(_text(resource, "MaxUnits"), f"resource {uid}") == spec["units"],
                 f"resource input changed: {uid}")
        v2._check_witnessed_save_inputs(resource, f"resource {uid}", {
            "ActualOvertimeWork": matrix.ZERO, "BookingType": "0"})
    assignments = _rows(result, "Assignments")
    expected_assignments = _rows(fixed, "Assignments")
    _require(list(assignments) == list(expected_assignments), "assignment declaration order changed")
    _require(set(assignments) == set(expected_assignments), "assignment UID set changed")
    spans = {}
    for uid, expected in expected_assignments.items():
        row = assignments[uid]
        spec = assignment_specs[uid]
        _check_row(row, expected, ASSIGNMENT_OUTPUTS | {"RegularWork", "Units"},
                   v2.ASSIGNMENT_SAVE_FIELDS | {"RegularWork", "TimephasedData"},
                   f"assignment {uid}")
        _require(_text(row, "GUID") == matrix.guid("assignment", uid) and
                 _text(row, "TaskUID") == str(task_specs[spec["task"]]["uid"]) and
                 _text(row, "ResourceUID") == str(uid), f"assignment linkage changed: {uid}")
        _require(v2._decimal(_text(row, "Units"), f"assignment {uid}") == spec["units"] and
                 _text(row, "RegularWork") in (None, matrix.duration(spec["work"])),
                 f"assignment Units/Work changed: {uid}")
        v2._check_witnessed_save_inputs(row, f"assignment {uid}", {
            "ActualOvertimeWork": matrix.ZERO, "OvertimeWork": matrix.ZERO,
            "RemainingOvertimeWork": matrix.ZERO, "BookingType": "0",
            "FixedMaterial": "0", "HasFixedRateUnits": "1"})
        spans[uid] = (_date(row, "Start", str(uid)), _date(row, "Finish", str(uid)))
        # Any newly written timephased allocation must be identical in total
        # work, inside the declared assignment span, and use only work Type 1.
        timephased = row.findall("p:TimephasedData", NS)
        if timephased:
            total = 0
            for period in timephased:
                _require(_text(period, "Type") == "1" and
                         _text(period, "UID") == str(uid) and
                         _text(period, "Unit") == "1" and len(period) == 6,
                         f"assignment timephased shape changed: {uid}")
                start, end = _date(period, "Start", str(uid)), _date(period, "Finish", str(uid))
                _require(spans[uid][0] <= start < end <= spans[uid][1],
                         f"assignment timephased span changed: {uid}")
                value = _text(period, "Value")
                _require(value is not None and re.fullmatch(r"PT([0-9]+)H([0-9]+)M([0-9]+)S", value) is not None,
                         f"assignment timephased Work invalid: {uid}")
                hours, minutes, seconds = (int(x) for x in re.fullmatch(
                    r"PT([0-9]+)H([0-9]+)M([0-9]+)S", value).groups())
                total += hours * 3600 + minutes * 60 + seconds
            _require(total == spec["work"] * 3600,
                     f"assignment timephased Work changed: {uid}")
    return {"tasks": observed, "assignments": spans,
            "build_number": _text(result, "BuildNumber"),
            "project_finish": _date(result, "FinishDate", "project"),
            "project_guid": _text(result, "GUID")}


def analyze(payload: bytes) -> dict:
    native_identity = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    record = {"schema": SCHEMA, "experiment_id": matrix.EXPERIMENT_ID,
              "preregistration_id": matrix.PREREGISTRATION_ID,
              "input_identity": {"path": str(matrix.FIXTURE), "bytes": matrix.INPUT_BYTES,
                                 "sha256": matrix.INPUT_SHA256},
              "native_return": native_identity,
              "decision": {"native_v3_supported": False,
                           "machine_predicates_match_candidate": False,
                           "production_rc01_correction_authorized": False,
                           "p1_g2_met": False}}
    try:
        lineage = verified_lineage()
        data = _native_inputs(payload)
    except (NativeEvidenceError, KeyError, ValueError, OSError) as error:
        record["classification"] = {"verdict": "V3_INPUT_CONTRACT_VIOLATED",
                                    "reason": str(error)}
        return record
    record["native_build"] = data["build_number"]
    record["evidence_lineage"] = lineage
    if native_identity == {"bytes": matrix.INPUT_BYTES, "sha256": matrix.INPUT_SHA256} or not isinstance(data["build_number"], str) or v2.NATIVE_BUILD.fullmatch(data["build_number"]) is None:
        record["classification"] = {"verdict": "V3_NETWORKED_ASSIGNMENT_ENVELOPE_INCONCLUSIVE",
                                    "reason": "NOT_RUN_UNRECALCULATED_INPUT_OR_NO_NATIVE_BUILD"}
        return record
    expected = oracle.reference()
    tasks, _, assignment_specs = matrix.graph()
    checks = {}
    for name, spec in tasks.items():
        predicted, actual = expected[name], data["tasks"][name]
        for output, target in (("Start", "early_start"), ("Finish", "early_finish"),
                               ("EarlyStart", "early_start"), ("EarlyFinish", "early_finish"),
                               ("LateStart", "late_start"), ("LateFinish", "late_finish")):
            checks[f"{name}.{output}"] = actual[output] == predicted[target]
        checks[f"{name}.TotalSlack"] = actual["TotalSlack"] == predicted["total_slack_minutes"] * 10
        checks[f"{name}.FreeSlack"] = actual["FreeSlack"] == predicted["free_slack_minutes"] * 10
        checks[f"{name}.Critical"] = actual["Critical"] == predicted["critical"]
        # Duration is a recalculated task output measured by the PROJECT
        # calendar, not by elapsed time or any one assignment calendar.
        exact = _working_duration(predicted["early_start"], predicted["early_finish"])
        checks[f"{name}.Duration"] = actual["Duration"] == exact and actual["RemainingDuration"] == exact
    for uid, spec in assignment_specs.items():
        expected_span = expected[spec["task"]]["assignments"][uid]
        checks[f"assignment.{uid}.own_calendar"] = data["assignments"][uid] == expected_span
    checks["project_finish"] = data["project_finish"] == expected["_project_finish"]
    checks["A_order_twin"] = all(data["tasks"]["A"][f] == data["tasks"]["A-ORDER-TWIN"][f]
                                 for f in ("Start", "Finish", "EarlyStart", "EarlyFinish",
                                           "LateStart", "LateFinish", "TotalSlack", "FreeSlack", "Critical"))
    checks["C_calendar_identity_twin"] = all(
        data["tasks"]["C"][f] == data["tasks"]["C-CALENDAR-IDENTITY-TWIN"][f]
        for f in ("Start", "Finish", "EarlyStart", "EarlyFinish", "LateStart",
                  "LateFinish", "TotalSlack", "FreeSlack", "Critical"))
    checks["D_unique_late_driver"] = (expected["D-POST-LONG"]["late_start"] <
                                       expected["D-POST"]["late_start"] and
                                       expected["D"]["late_finish"] ==
                                       expected["D-POST-LONG"]["late_start"])
    checks["D_positive_free_float"] = expected["D"]["free_slack_minutes"] > 0
    gap_10h = next(uid for uid, spec in assignment_specs.items()
                   if spec["task"] == "GAP" and spec["role"] == "10H")
    gap_24h = next(uid for uid, spec in assignment_specs.items()
                   if spec["task"] == "GAP" and spec["role"] == "24H")
    checks["GAP_networked_resource_gap"] = (
        expected["GAP"]["assignments"][gap_10h][1] >
        expected["GAP"]["assignments"][gap_24h][1] and
        expected["GAP"]["early_finish"] == expected["GAP"]["assignments"][gap_10h][1])
    checks["nontrivial_late"] = all(expected[name]["late_start"] > expected[name]["early_start"]
                                     for name in matrix.CASES if name != "ADJACENT-RC01")
    checks["finish_driver_critical"] = expected["FINISH-DRIVER"]["critical"]
    mapping = matrix.root_mapping(ROOT / matrix.AUDIT)
    checks["all_ten_roots_mapped"] = len(mapping) == 10 and all(
        item["native_case"] in matrix.CASES and
        (not item["adjacent_case"] or item["adjacent_case"] in matrix.CASES)
        for item in mapping.values())
    support = all(checks.values())
    controls = all(checks[key] for key in ("FINISH-DRIVER.Start", "FINISH-DRIVER.Finish",
                                                "FINISH-DRIVER.TotalSlack", "finish_driver_critical",
                                                "A_order_twin", "C_calendar_identity_twin"))
    # Rejection requires a FULL coherent alternate model: task end-padding
    # preserves the declared duration when the assignment envelope is shorter.
    # Assignments always remain inside their task; mixed rules are inconclusive.
    alternative = oracle.padded_reference()
    def matches_padded(name: str) -> bool:
        row, predicted = data["tasks"][name], alternative[name]
        dates = (("Start", "early_start"), ("Finish", "early_finish"),
                 ("EarlyStart", "early_start"), ("EarlyFinish", "early_finish"),
                 ("LateStart", "late_start"), ("LateFinish", "late_finish"))
        expected_duration = _working_duration(predicted["early_start"], predicted["early_finish"])
        return (all(row[field] == predicted[key] for field, key in dates)
                and row["Duration"] == expected_duration
                and row["RemainingDuration"] == expected_duration
                and row["TotalSlack"] == predicted["total_slack_minutes"] * 10
                and row["FreeSlack"] == predicted["free_slack_minutes"] * 10
                and row["Critical"] == predicted["critical"])
    rejected = (not support and controls and
                all(matches_padded(name) for name in tasks) and
                all(data["assignments"][uid] == alternative[spec["task"]]["assignments"][uid]
                    for uid, spec in assignment_specs.items()) and
                data["project_finish"] == alternative["_project_finish"])
    verdict = ("V3_NETWORKED_ASSIGNMENT_ENVELOPE_SUPPORTED" if support else
               "V3_NETWORKED_ASSIGNMENT_ENVELOPE_REJECTED" if rejected else
               "V3_NETWORKED_ASSIGNMENT_ENVELOPE_INCONCLUSIVE")
    record["classification"] = {"verdict": verdict, "predicates": checks,
                                "controls_valid": controls,
                                "failed_predicates": sorted(k for k, ok in checks.items() if not ok)}
    record["root_to_native_case"] = mapping
    record["observations"] = {"tasks": {name: {key: value.isoformat() if isinstance(value, datetime) else value
                                               for key, value in row.items()}
                                             for name, row in data["tasks"].items()},
                              "assignments": {str(uid): [date.isoformat() for date in span]
                                              for uid, span in data["assignments"].items()}}
    # MSPDI BuildNumber and output dates can be hand-authored (the synthetic
    # unit-test fixture does exactly that). Machine classification is NOT
    # independent proof of desktop execution. Production authorization always
    # requires a separate user-attested native provenance review and later PR.
    record["decision"]["machine_predicates_match_candidate"] = support
    record["decision"]["native_provenance"] = "UNVERIFIED_OPERATOR_ATTESTATION_REQUIRED"
    record["decision"]["production_rc01_correction_authorized"] = False
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native_return", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sources = {"V3 returned source": args.native_return,
               "V3 fixed fixture": ROOT / matrix.FIXTURE,
               "BOILER applicability audit": ROOT / matrix.AUDIT,
               "V2 native result": ROOT / "docs/evidence/p1-g2-rc01-native-v2-valid-return-2026-09-28.json",
               "BOILER counterfactual result": ROOT / "docs/evidence/p1-g2-rc01-boiler-counterfactual-reviewed-v3-2026-09-28.json"}
    sources.update({f"existing append-only evidence {path.name}": path
                    for path in (ROOT / "docs/evidence").iterdir() if path.is_file()})
    sources.update({f"V3 evidence tool {path.name}": path for path in
                    (Path(__file__), Path(matrix.__file__), Path(oracle.__file__))})
    v2.refuse_output_alias(args.output, sources)
    original = args.native_return.read_bytes()
    result = json.dumps(analyze(original), sort_keys=True, indent=2) + "\n"
    _require(args.native_return.read_bytes() == original, "native return changed during analysis")
    v2.write_output_safely(args.output, result, sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
