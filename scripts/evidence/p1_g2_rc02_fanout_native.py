#!/usr/bin/env python3
"""Analyze the bounded P1-G2 RC02 inactive fan-out Microsoft Project return.

Evidence tooling only. It does not change or emulate production scheduling.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence import p1_g2_rc02_fanout_native_generate as generate

NS = {"p": "http://schemas.microsoft.com/project"}
SCHEMA = "sto-p1-g2-rc02-fanout-native-v1"
INPUT_BYTES = 64_729
INPUT_SHA256 = "402bf7a9a143f7958fdf76589e7d566c2c0b84fa7593c4a06098e4fb29ed00b2"
SENTINEL = 12_345

FIELDS = (
    "UID", "ID", "Active", "Start", "Finish", "EarlyStart", "EarlyFinish",
    "LateStart", "LateFinish", "TotalSlack", "FreeSlack", "Critical",
    "Duration", "Manual", "ConstraintType", "CalendarUID", "PercentComplete",
)
DATE_FIELDS = ("Start", "Finish", "EarlyStart", "EarlyFinish", "LateStart", "LateFinish")

PAIR_ROLES = {
    "A": {"PRED": 24, "MID": 48, "S1": 96, "S2": 24},
    "B": {"PRED": 24, "MID": 48, "OTHER": 96, "S1": 24, "S2": 96},
    "C": {"PRED": 24, "MID": 48, "O1": 96, "O2": 120, "S1": 24, "S2": 48},
}

EXPECTED = {
    "RC02-FANOUT-FINISH-DRIVER": ("1", ()),
    "RC02-FO-A-A-PRED": ("2", ()),
    "RC02-FO-A-A-MID": ("3", ("2",)),
    "RC02-FO-A-A-S1": ("4", ("3",)),
    "RC02-FO-A-A-S2": ("5", ("3",)),
    "RC02-FO-A-I-PRED": ("6", ()),
    "RC02-FO-A-I-MID": ("7", ("6",)),
    "RC02-FO-A-I-S1": ("8", ("7",)),
    "RC02-FO-A-I-S2": ("9", ("7",)),
    "RC02-FO-B-A-PRED": ("10", ()),
    "RC02-FO-B-A-MID": ("11", ("10",)),
    "RC02-FO-B-A-OTHER": ("12", ()),
    "RC02-FO-B-A-S1": ("13", ("11",)),
    "RC02-FO-B-A-S2": ("14", ("11", "12")),
    "RC02-FO-B-I-PRED": ("15", ()),
    "RC02-FO-B-I-MID": ("16", ("15",)),
    "RC02-FO-B-I-OTHER": ("17", ()),
    "RC02-FO-B-I-S1": ("18", ("16",)),
    "RC02-FO-B-I-S2": ("19", ("16", "17")),
    "RC02-FO-C-A-PRED": ("20", ()),
    "RC02-FO-C-A-MID": ("21", ("20",)),
    "RC02-FO-C-A-O1": ("22", ()),
    "RC02-FO-C-A-O2": ("23", ()),
    "RC02-FO-C-A-S1": ("24", ("21", "22")),
    "RC02-FO-C-A-S2": ("25", ("21", "23")),
    "RC02-FO-C-I-PRED": ("26", ()),
    "RC02-FO-C-I-MID": ("27", ("26",)),
    "RC02-FO-C-I-O1": ("28", ()),
    "RC02-FO-C-I-O2": ("29", ()),
    "RC02-FO-C-I-S1": ("30", ("27", "28")),
    "RC02-FO-C-I-S2": ("31", ("27", "29")),
}
REQUIRED = frozenset(EXPECTED)
INACTIVE = frozenset({"RC02-FO-A-I-MID", "RC02-FO-B-I-MID", "RC02-FO-C-I-MID"})
HOURS = {"RC02-FANOUT-FINISH-DRIVER": 336} | {
    f"RC02-FO-{pair}-{twin}-{role}": hours
    for pair, roles in PAIR_ROLES.items()
    for twin in ("A", "I")
    for role, hours in roles.items()
}


def text(task: ET.Element, field: str) -> str | None:
    node = task.find(f"p:{field}", NS)
    return None if node is None else node.text


def date_value(value: object) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo is None else None


def slack_units_between(start: object, finish: object) -> int | None:
    a, b = date_value(start), date_value(finish)
    if a is None or b is None:
        return None
    seconds = (b - a).total_seconds()
    return int(seconds / 6) if seconds % 6 == 0 else None


def eq(rows: dict[str, dict[str, object]], left: tuple[str, str], right: tuple[str, str]) -> bool:
    a = date_value(rows[left[0]].get(left[1]))
    b = date_value(rows[right[0]].get(right[1]))
    return a is not None and b is not None and a == b


def parse(payload: bytes) -> tuple[dict[str, str | None], dict[str, dict[str, object]]]:
    root = ET.fromstring(payload)
    project = {
        "build_number": root.findtext("p:BuildNumber", default=None, namespaces=NS),
        "name": root.findtext("p:Name", default=None, namespaces=NS),
        "start": root.findtext("p:StartDate", default=None, namespaces=NS),
        "finish": root.findtext("p:FinishDate", default=None, namespaces=NS),
    }
    rows: dict[str, dict[str, object]] = {}
    for task in root.findall("p:Tasks/p:Task", NS):
        name = text(task, "Name")
        if not name:
            continue
        if name in rows:
            raise SystemExit(f"native return duplicates matrix task name: {name}")
        row: dict[str, object] = {field: text(task, field) for field in FIELDS}
        links = [
            {
                "predecessor_uid": link.findtext("p:PredecessorUID", default="", namespaces=NS),
                "type": link.findtext("p:Type", default="", namespaces=NS),
                "link_lag": link.findtext("p:LinkLag", default="", namespaces=NS),
            }
            for link in task.findall("p:PredecessorLink", NS)
        ]
        row["predecessor_links"] = links
        row["predecessor_uids"] = [link["predecessor_uid"] for link in links]
        rows[name] = row
    validate_rows(rows)
    return project, rows


def read(path: Path) -> tuple[dict[str, str | None], dict[str, dict[str, object]]]:
    return parse(path.read_bytes())


def validate_rows(rows: dict[str, dict[str, object]]) -> None:
    missing = sorted(REQUIRED - rows.keys())
    if missing:
        raise SystemExit("native return is missing fan-out matrix tasks: " + ", ".join(missing))
    wrong_active = sorted(
        name for name in REQUIRED
        if rows[name].get("Active") != ("0" if name in INACTIVE else "1")
    )
    if wrong_active:
        raise SystemExit("native return changed fan-out Active flags: " + ", ".join(wrong_active))
    wrong_identity = sorted(
        name for name, (uid, _) in EXPECTED.items() if rows[name].get("UID") != uid
    )
    if wrong_identity:
        raise SystemExit("native return changed fan-out task identity: " + ", ".join(wrong_identity))
    wrong_links: list[str] = []
    for name, (_, predecessor_uids) in EXPECTED.items():
        expected = sorted((uid, "1", "0") for uid in predecessor_uids)
        actual = sorted(
            (str(link["predecessor_uid"]), str(link["type"]), str(link["link_lag"]))
            for link in rows[name]["predecessor_links"]
        )
        if actual != expected:
            wrong_links.append(name)
    if wrong_links:
        raise SystemExit(
            "native return changed zero-lag FS fan-out topology: " + ", ".join(wrong_links)
        )
    for name in sorted(REQUIRED):
        row = rows[name]
        for field in DATE_FIELDS:
            if date_value(row.get(field)) is None:
                raise SystemExit(f"native return missing or invalid date: {name}.{field}")
        for field in ("FreeSlack", "TotalSlack"):
            value = row.get(field)
            if not isinstance(value, str) or not value.lstrip("-").isdigit():
                raise SystemExit(f"native return missing or invalid slack: {name}.{field}")
        expected = {
            "Duration": f"PT{HOURS[name]}H0M0S",
            "Manual": "0",
            "ConstraintType": "0",
            "CalendarUID": "1",
            "PercentComplete": "0",
        }
        for field, value in expected.items():
            if row.get(field) != value:
                raise SystemExit(f"native return changed fixed fan-out input: {name}.{field}")


def control_checks(rows: dict[str, dict[str, object]]) -> dict[str, bool]:
    def at(name: str, field: str) -> datetime:
        value = date_value(rows[name][field])
        assert value is not None
        return value

    driver = "RC02-FANOUT-FINISH-DRIVER"
    project_start, project_finish = at(driver, "Start"), at(driver, "Finish")
    checks: dict[str, bool] = {
        "finish_driver": (
            project_finish - project_start == timedelta(hours=336)
            and at(driver, "LateStart") == project_start
            and at(driver, "LateFinish") == project_finish
        ),
        "all_observed_spans_and_early_dates": all(
            at(name, "Finish") - at(name, "Start") == timedelta(hours=HOURS[name])
            and at(name, "LateFinish") - at(name, "LateStart") == timedelta(hours=HOURS[name])
            and at(name, "EarlyStart") == at(name, "Start")
            and at(name, "EarlyFinish") == at(name, "Finish")
            for name in REQUIRED
        ),
    }

    for pair in "ABC":
        p = f"RC02-FO-{pair}-A-"
        pred, mid, s1, s2 = (p + role for role in ("PRED", "MID", "S1", "S2"))
        checks[f"pair_{pair.lower()}_active_mid_forward"] = at(mid, "Start") == at(pred, "Finish")
        if pair == "A":
            checks[f"pair_{pair.lower()}_active_successors_forward"] = (
                at(s1, "Start") == at(mid, "Finish")
                and at(s2, "Start") == at(mid, "Finish")
            )
        elif pair == "B":
            other = p + "OTHER"
            checks[f"pair_{pair.lower()}_active_successors_forward"] = (
                at(s1, "Start") == at(mid, "Finish")
                and at(s2, "Start") == max(at(mid, "Finish"), at(other, "Finish"))
                and at(other, "Start") == project_start
            )
            checks[f"pair_{pair.lower()}_active_other_backward"] = at(other, "LateFinish") == at(s2, "LateStart")
        else:
            o1, o2 = p + "O1", p + "O2"
            checks[f"pair_{pair.lower()}_active_successors_forward"] = (
                at(s1, "Start") == max(at(mid, "Finish"), at(o1, "Finish"))
                and at(s2, "Start") == max(at(mid, "Finish"), at(o2, "Finish"))
                and at(o1, "Start") == project_start
                and at(o2, "Start") == project_start
            )
            checks[f"pair_{pair.lower()}_active_other_backward"] = (
                at(o1, "LateFinish") == at(s1, "LateStart")
                and at(o2, "LateFinish") == at(s2, "LateStart")
            )
        checks[f"pair_{pair.lower()}_active_backward"] = (
            at(s1, "LateFinish") == project_finish
            and at(s2, "LateFinish") == project_finish
            and at(mid, "LateFinish") == min(at(s1, "LateStart"), at(s2, "LateStart"))
            and at(pred, "LateFinish") == at(mid, "LateStart")
        )
        pred_free = int(rows[pred]["FreeSlack"])
        mid_free = int(rows[mid]["FreeSlack"])
        direct_mid_gaps = [
            slack_units_between(rows[mid]["EarlyFinish"], rows[s1]["EarlyStart"]),
            slack_units_between(rows[mid]["EarlyFinish"], rows[s2]["EarlyStart"]),
        ]
        checks[f"pair_{pair.lower()}_active_free_slack"] = (
            pred_free == slack_units_between(rows[pred]["EarlyFinish"], rows[mid]["EarlyStart"])
            and None not in direct_mid_gaps
            and mid_free == min(int(value) for value in direct_mid_gaps if value is not None)
        )

    checks["pair_a_late_discriminator"] = at("RC02-FO-A-A-S1", "LateStart") < at("RC02-FO-A-A-S2", "LateStart")
    checks["pair_b_late_discriminator"] = at("RC02-FO-B-A-S2", "LateStart") < at("RC02-FO-B-A-S1", "LateStart")
    checks["pair_c_late_discriminator"] = at("RC02-FO-C-A-S2", "LateStart") < at("RC02-FO-C-A-S1", "LateStart")

    # The inactive successors are the discriminator under test. Require their
    # terminal late boundaries to stay distinct in the same deliberately
    # reversed pattern as the controls; otherwise "earliest" and "latest" can
    # collapse to the same coordinate and falsely look like a proven rule.
    for pair in "ABC":
        p = f"RC02-FO-{pair}-I-"
        s1, s2 = p + "S1", p + "S2"
        checks[f"pair_{pair.lower()}_inactive_successors_terminal"] = (
            at(s1, "LateFinish") == project_finish
            and at(s2, "LateFinish") == project_finish
        )
    checks["pair_a_inactive_late_discriminator"] = at("RC02-FO-A-I-S1", "LateStart") < at("RC02-FO-A-I-S2", "LateStart")
    checks["pair_b_inactive_late_discriminator"] = at("RC02-FO-B-I-S2", "LateStart") < at("RC02-FO-B-I-S1", "LateStart")
    checks["pair_c_inactive_late_discriminator"] = at("RC02-FO-C-I-S2", "LateStart") < at("RC02-FO-C-I-S1", "LateStart")
    return checks


def _inactive_pair(rows: dict[str, dict[str, object]], pair: str) -> dict[str, object]:
    p = f"RC02-FO-{pair}-I-"
    pred, mid, s1, s2 = (p + role for role in ("PRED", "MID", "S1", "S2"))
    pred_late_finish = date_value(rows[pred]["LateFinish"])
    s1_late_start = date_value(rows[s1]["LateStart"])
    s2_late_start = date_value(rows[s2]["LateStart"])
    assert pred_late_finish is not None and s1_late_start is not None and s2_late_start is not None
    earliest = min(s1_late_start, s2_late_start)
    latest = max(s1_late_start, s2_late_start)
    return {
        "predecessor_late_finish": pred_late_finish.isoformat(),
        "s1_late_start": s1_late_start.isoformat(),
        "s2_late_start": s2_late_start.isoformat(),
        "earliest_successor": "S1" if s1_late_start < s2_late_start else "S2",
        "matches_earliest_successor": pred_late_finish == earliest,
        "matches_latest_successor": pred_late_finish == latest,
        "matches_s1": pred_late_finish == s1_late_start,
        "matches_s2": pred_late_finish == s2_late_start,
        "inactive_edge_gap": slack_units_between(rows[pred]["EarlyFinish"], rows[mid]["EarlyStart"]),
        "direct_successor_gaps": {
            "S1": slack_units_between(rows[pred]["EarlyFinish"], rows[s1]["EarlyStart"]),
            "S2": slack_units_between(rows[pred]["EarlyFinish"], rows[s2]["EarlyStart"]),
        },
    }


def classify(rows: dict[str, dict[str, object]]) -> dict[str, object]:
    validate_rows(rows)
    controls = control_checks(rows)
    controls_valid = all(controls.values())

    pair = {letter: _inactive_pair(rows, letter) for letter in "ABC"}

    forward_checks = {
        "pair_a_s1_passthrough": eq(rows, ("RC02-FO-A-I-S1", "Start"), ("RC02-FO-A-I-PRED", "Finish")),
        "pair_a_s2_passthrough": eq(rows, ("RC02-FO-A-I-S2", "Start"), ("RC02-FO-A-I-PRED", "Finish")),
        "pair_b_s1_passthrough": eq(rows, ("RC02-FO-B-I-S1", "Start"), ("RC02-FO-B-I-PRED", "Finish")),
        "pair_b_s2_competitor_drives": eq(rows, ("RC02-FO-B-I-S2", "Start"), ("RC02-FO-B-I-OTHER", "Finish")),
        "pair_c_s1_competitor_drives": eq(rows, ("RC02-FO-C-I-S1", "Start"), ("RC02-FO-C-I-O1", "Finish")),
        "pair_c_s2_competitor_drives": eq(rows, ("RC02-FO-C-I-S2", "Start"), ("RC02-FO-C-I-O2", "Finish")),
    }
    forward_passthrough = controls_valid and all(forward_checks.values())

    earliest = controls_valid and all(pair[letter]["matches_earliest_successor"] for letter in "ABC")
    latest = controls_valid and all(pair[letter]["matches_latest_successor"] for letter in "ABC")
    first_s1 = controls_valid and all(pair[letter]["matches_s1"] for letter in "ABC")

    if earliest:
        backward = "EARLIEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED"
    elif latest:
        backward = "LATEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED"
    elif first_s1:
        backward = "S1_SUCCESSOR_LATE_BOUNDARY_OBSERVED"
    else:
        backward = "NO_SINGLE_TESTED_FANOUT_BACKWARD_RULE_ESTABLISHED"

    c_pred = rows["RC02-FO-C-I-PRED"]
    observed_free = int(c_pred["FreeSlack"])
    inactive_gap = int(pair["C"]["inactive_edge_gap"]) if pair["C"]["inactive_edge_gap"] is not None else None
    direct_values = pair["C"]["direct_successor_gaps"]
    direct_min = min(int(v) for v in direct_values.values() if v is not None)
    sentinel_changed = observed_free != SENTINEL
    matches_inactive = inactive_gap is not None and observed_free == inactive_gap
    matches_direct = observed_free == direct_min
    if not sentinel_changed:
        free_slack = "SENTINEL_RETAINED_NOT_ESTABLISHED"
    elif matches_inactive and not matches_direct:
        free_slack = "SENTINEL_CHANGED_MATCHES_INACTIVE_EDGE_GAP"
    elif matches_direct and not matches_inactive:
        free_slack = "SENTINEL_CHANGED_MATCHES_DIRECT_SUCCESSOR_MIN_GAP"
    else:
        free_slack = "SENTINEL_CHANGED_OTHER_OR_AMBIGUOUS_VALUE"

    late_deltas = {
        letter: slack_units_between(
            rows[f"RC02-FO-{letter}-A-PRED"]["LateFinish"],
            rows[f"RC02-FO-{letter}-I-PRED"]["LateFinish"],
        )
        for letter in "ABC"
    }
    paired_late_effect = all(value == 48 * 600 for value in late_deltas.values())

    diagnostic_authorized = (
        controls_valid
        and forward_passthrough
        and backward == "EARLIEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED"
        and paired_late_effect
        and free_slack == "SENTINEL_CHANGED_MATCHES_INACTIVE_EDGE_GAP"
    )
    verdict = (
        "FANOUT_EARLIEST_LATE_BOUNDARY_WITH_INACTIVE_EDGE_FREE_SLACK_OBSERVED"
        if diagnostic_authorized
        else "FANOUT_NATIVE_RULE_NOT_ESTABLISHED"
    )

    return {
        "verdict": verdict,
        "controls": {"valid": controls_valid, "checks": controls},
        "components": {
            "forward_semantic": (
                "ZERO_DURATION_FANOUT_FORWARD_PASSTHROUGH_SUPPORTED"
                if forward_passthrough else "NOT_ESTABLISHED"
            ),
            "backward_semantic": backward,
            "free_slack_observation": free_slack,
        },
        "forward_checks": forward_checks,
        "inactive_pairs": pair,
        "paired_late_delta_units": late_deltas,
        "paired_late_effect_matches_removed_mid_duration": paired_late_effect,
        "free_slack_sentinel": {
            "seeded_value": SENTINEL,
            "observed_value": observed_free,
            "sentinel_changed": sentinel_changed,
            "inactive_edge_gap": inactive_gap,
            "direct_successor_gaps": direct_values,
            "direct_successor_min_gap": direct_min,
            "matches_inactive_edge_gap": matches_inactive,
            "matches_direct_successor_min_gap": matches_direct,
        },
        "validated_topology": {
            name: {"uid": rows[name]["UID"], "predecessor_links": rows[name]["predecessor_links"]}
            for name in sorted(EXPECTED)
        },
        "observations": {name: rows[name] for name in sorted(REQUIRED)},
        "decision": {
            "boiler_counterfactual_rerun_authorized": diagnostic_authorized,
            "production_scheduler_change_authorized": False,
            "p1_g2_closed": False,
            "p1_gate": "4/5 IN PROGRESS",
            "p2_started": False,
        },
    }


def analyze(payload: bytes, *, owner_confirmed_opened_input: bool = False) -> dict[str, object]:
    generated = generate.build_fixture()
    if len(generated) != INPUT_BYTES or hashlib.sha256(generated).hexdigest() != INPUT_SHA256:
        raise SystemExit("fan-out generator no longer matches pinned input identity")
    project, rows = parse(payload)
    classification = classify(rows)
    if not owner_confirmed_opened_input:
        classification["decision"]["boiler_counterfactual_rerun_authorized"] = False
    return {
        "schema": SCHEMA,
        "input": {
            "bytes": INPUT_BYTES,
            "sha256": INPUT_SHA256,
            "project_name": generate.PROJECT_NAME,
            "sentinel": {
                "task_uid": "26",
                "task_name": "RC02-FO-C-I-PRED",
                "field": "FreeSlack",
                "seeded_value": SENTINEL,
            },
        },
        "native_return": {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "project": project,
        "input_lineage": {
            "owner_confirmed_opened_pinned_input": owner_confirmed_opened_input,
            "machine_proven_from_return_alone": False,
            "note": (
                "The return hash and topology cannot by themselves prove which input was opened; "
                "authorization requires owner confirmation of the pinned generated input."
            ),
        },
        "classification": classification,
    }


def serialize(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=False) + "\n"


def require_separate_output(source: Path, output: Path) -> None:
    if output.resolve() == source.resolve() or (output.exists() and output.samefile(source)):
        raise SystemExit("output must be separate from native return (including file aliases)")


def write_candidate(source: Path, output: Path, payload: str) -> None:
    require_separate_output(source, output)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        require_separate_output(source, output)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("native_return", type=Path)
    parser.add_argument("--confirm-opened-input", action="store_true")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.output:
        require_separate_output(args.native_return, args.output)
    payload = serialize(
        analyze(
            args.native_return.read_bytes(),
            owner_confirmed_opened_input=args.confirm_opened_input,
        )
    )
    if args.check:
        if args.check.read_bytes() != payload.encode("utf-8"):
            raise SystemExit("committed fan-out evidence differs from exact analyzer output")
        print("committed fan-out evidence matches exact analyzer output")
    elif args.output:
        write_candidate(args.native_return, args.output, payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
