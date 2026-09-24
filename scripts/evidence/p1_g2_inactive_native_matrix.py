#!/usr/bin/env python3
"""Classify the P1-G2 RC02 synthetic Microsoft Project native return.

This is evidence tooling only. It does not calculate a replacement schedule.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

NS = {"p": "http://schemas.microsoft.com/project"}

REQUIRED = {
    "RC02-FINISH-DRIVER",
    "RC02-A-A-PRED", "RC02-A-A-MID", "RC02-A-A-SUCC",
    "RC02-A-I-PRED", "RC02-A-I-MID", "RC02-A-I-SUCC",
    "RC02-B-A-PRED", "RC02-B-A-MID", "RC02-B-A-OTHER", "RC02-B-A-SUCC",
    "RC02-B-I-PRED", "RC02-B-I-MID", "RC02-B-I-OTHER", "RC02-B-I-SUCC",
    "RC02-C-A-PRED", "RC02-C-A-MID", "RC02-C-A-OTHER", "RC02-C-A-SUCC",
    "RC02-C-I-PRED", "RC02-C-I-MID", "RC02-C-I-OTHER", "RC02-C-I-SUCC",
}
INACTIVE = {"RC02-A-I-MID", "RC02-B-I-MID", "RC02-C-I-MID"}
EXPECTED = {
    "RC02-FINISH-DRIVER": ("1", ()),
    "RC02-A-A-PRED": ("2", ()),
    "RC02-A-A-MID": ("3", ("2",)),
    "RC02-A-A-SUCC": ("4", ("3",)),
    "RC02-A-I-PRED": ("5", ()),
    "RC02-A-I-MID": ("6", ("5",)),
    "RC02-A-I-SUCC": ("7", ("6",)),
    "RC02-B-A-PRED": ("8", ()),
    "RC02-B-A-MID": ("9", ("8",)),
    "RC02-B-A-OTHER": ("10", ()),
    "RC02-B-A-SUCC": ("11", ("9", "10")),
    "RC02-B-I-PRED": ("12", ()),
    "RC02-B-I-MID": ("13", ("12",)),
    "RC02-B-I-OTHER": ("14", ()),
    "RC02-B-I-SUCC": ("15", ("13", "14")),
    "RC02-C-A-PRED": ("16", ()),
    "RC02-C-A-MID": ("17", ("16",)),
    "RC02-C-A-OTHER": ("18", ()),
    "RC02-C-A-SUCC": ("19", ("17", "18")),
    "RC02-C-I-PRED": ("20", ()),
    "RC02-C-I-MID": ("21", ("20",)),
    "RC02-C-I-OTHER": ("22", ()),
    "RC02-C-I-SUCC": ("23", ("21", "22")),
}

FIELDS = (
    "UID", "ID", "Active", "Start", "Finish", "EarlyStart", "EarlyFinish",
    "LateStart", "LateFinish", "TotalSlack", "FreeSlack", "Critical",
    "Duration", "Manual", "ConstraintType", "CalendarUID", "PercentComplete",
)
DATE_FIELDS = ("Start", "Finish", "EarlyStart", "EarlyFinish", "LateStart", "LateFinish")
# Fixed input contract, not a scheduler or a rule for arbitrary inactive tasks.
PAIR_HOURS = {
    "A": {"PRED": 48, "MID": 72, "SUCC": 24},
    "B": {"PRED": 72, "MID": 48, "OTHER": 24, "SUCC": 24},
    "C": {"PRED": 24, "MID": 48, "OTHER": 96, "SUCC": 24},
}
HOURS = {"RC02-FINISH-DRIVER": 240} | {
    f"RC02-{pair}-{twin}-{role}": hours
    for pair, roles in PAIR_HOURS.items()
    for twin in ("A", "I") for role, hours in roles.items()
}
SCHEMA = "sto-p1-g2-rc02-native-matrix-v4"



def text(task: ET.Element, field: str) -> str | None:
    node = task.find(f"p:{field}", NS)
    return None if node is None else node.text


def read(path: Path) -> tuple[dict[str, str | None], dict[str, dict[str, object]]]:
    return parse(path.read_bytes())


def parse(payload: bytes) -> tuple[dict[str, str | None], dict[str, dict[str, object]]]:
    """Read the exact bytes whose digest the evidence record will retain."""
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
                "predecessor_uid": link.findtext(
                    "p:PredecessorUID", default="", namespaces=NS
                ),
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


def validate_rows(rows: dict[str, dict[str, object]]) -> None:
    missing = sorted(REQUIRED - rows.keys())
    if missing:
        raise SystemExit("native return is missing matrix tasks: " + ", ".join(missing))
    wrong_active = sorted(
        name for name in REQUIRED
        if rows[name].get("Active") != ("0" if name in INACTIVE else "1")
    )
    if wrong_active:
        raise SystemExit("native return changed matrix Active flags: " + ", ".join(wrong_active))
    wrong_identity = sorted(
        name for name, (uid, _) in EXPECTED.items()
        if rows[name]["UID"] != uid
    )
    if wrong_identity:
        raise SystemExit(
            "native return changed matrix task identity: " + ", ".join(wrong_identity)
        )
    wrong_links: list[str] = []
    for name, (_, predecessor_uids) in EXPECTED.items():
        expected_links = sorted((uid, "1", "0") for uid in predecessor_uids)
        actual_links = sorted(
            (
                str(link["predecessor_uid"]),
                str(link["type"]),
                str(link["link_lag"]),
            )
            for link in rows[name]["predecessor_links"]
        )
        if actual_links != expected_links:
            wrong_links.append(name)
    if wrong_links:
        raise SystemExit(
            "native return changed zero-lag FS matrix relationships: "
            + ", ".join(wrong_links)
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
            "Duration": f"PT{HOURS[name]}H0M0S", "Manual": "0",
            "ConstraintType": "0", "CalendarUID": "1", "PercentComplete": "0",
        }
        for field, value in expected.items():
            if row.get(field) != value:
                raise SystemExit(f"native return changed fixed matrix input: {name}.{field}")


def date_value(value: object) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo is None else None


def eq(rows: dict[str, dict[str, object]], left: tuple[str, str], right: tuple[str, str]) -> bool:
    a = date_value(rows[left[0]].get(left[1]))
    b = date_value(rows[right[0]].get(right[1]))
    return a is not None and b is not None and a == b


def slack_units_between(start: object, finish: object) -> int | None:
    """Return MSPDI slack units (tenths of a minute) for this 24-hour matrix."""
    a, b = date_value(start), date_value(finish)
    if a is None or b is None:
        return None
    seconds = (b - a).total_seconds()
    return int(seconds / 6) if seconds % 6 == 0 else None


def control_checks(rows: dict[str, dict[str, object]]) -> dict[str, bool]:
    """Prove the all-active counter-case and the fixed 24-hour experiment."""
    def at(name: str, field: str) -> datetime:
        value = date_value(rows[name][field])
        assert value is not None  # validate_rows has already checked every coordinate.
        return value

    driver = "RC02-FINISH-DRIVER"
    start, finish = at(driver, "Start"), at(driver, "Finish")
    checks = {
        "finish_driver": finish - start == timedelta(hours=240)
        and at(driver, "LateStart") == start and at(driver, "LateFinish") == finish,
        "all_observed_spans_and_early_dates": all(
            at(name, "Finish") - at(name, "Start") == timedelta(hours=HOURS[name])
            and at(name, "LateFinish") - at(name, "LateStart") == timedelta(hours=HOURS[name])
            and at(name, "EarlyStart") == at(name, "Start")
            and at(name, "EarlyFinish") == at(name, "Finish")
            for name in REQUIRED
        ),
    }
    for pair, roles in PAIR_HOURS.items():
        prefix = f"RC02-{pair}-A-"
        pred, mid, succ = (prefix + role for role in ("PRED", "MID", "SUCC"))
        boundaries = [at(mid, "Finish")]
        if "OTHER" in roles:
            boundaries.append(at(prefix + "OTHER", "Finish"))
        checks[f"pair_{pair.lower()}_active_forward"] = (
            at(mid, "Start") == at(pred, "Finish")
            and at(succ, "Start") == max(boundaries)
        )
        checks[f"pair_{pair.lower()}_active_backward"] = (
            at(pred, "LateFinish") == at(mid, "LateStart")
            and at(mid, "LateFinish") == at(succ, "LateStart")
            and at(succ, "LateFinish") == finish
            and ("OTHER" not in roles or
                 at(prefix + "OTHER", "LateFinish") == at(succ, "LateStart"))
        )
        checks[f"pair_{pair.lower()}_matched_roots_and_terminal"] = all(
            at(f"RC02-{pair}-{twin}-{role}", "Start") == start
            for twin in ("A", "I") for role in roles if role in ("PRED", "OTHER")
        ) and at(f"RC02-{pair}-I-SUCC", "LateFinish") == finish
        checks[f"pair_{pair.lower()}_active_free_slack"] = (
            int(rows[pred]["FreeSlack"]) ==
            slack_units_between(rows[pred]["EarlyFinish"], rows[mid]["EarlyStart"])
            and int(rows[mid]["FreeSlack"]) ==
            slack_units_between(rows[mid]["EarlyFinish"], rows[succ]["EarlyStart"])
        )
    checks["pair_b_competing_path_is_earlier"] = (
        at("RC02-B-I-OTHER", "Finish") < at("RC02-B-I-PRED", "Finish")
    )
    checks["pair_c_other_drives_both_twins"] = (
        at("RC02-C-I-OTHER", "Finish") > at("RC02-C-I-PRED", "Finish")
        and at("RC02-C-I-SUCC", "Start") == at("RC02-C-I-OTHER", "Finish")
        and at("RC02-C-A-SUCC", "Start") == at("RC02-C-I-SUCC", "Start")
    )
    return checks


def classify(rows: dict[str, dict[str, object]]) -> dict[str, object]:
    validate_rows(rows)
    controls = control_checks(rows)
    controls_valid = all(controls.values())
    # Pair A distinguishes "drop both endpoint edges" from date pass-through.
    a_drop = eq(rows, ("RC02-A-I-SUCC", "Start"), ("RC02-FINISH-DRIVER", "Start"))
    a_passthrough = eq(rows, ("RC02-A-I-SUCC", "Start"), ("RC02-A-I-PRED", "Finish"))

    # Pair B adds an ordinary active predecessor. OTHER finishes first, so the
    # inactive path must still contribute a date boundary if PRED drives.
    b_drop = eq(rows, ("RC02-B-I-SUCC", "Start"), ("RC02-B-I-OTHER", "Finish"))
    b_passthrough = eq(rows, ("RC02-B-I-SUCC", "Start"), ("RC02-B-I-PRED", "Finish"))

    # Pair C makes OTHER drive forward placement under either date hypothesis.
    # LateFinish reveals whether the inactive path still reaches SUCC backward.
    late_passthrough = all(
        eq(rows, (f"RC02-{pair}-I-PRED", "LateFinish"),
           (f"RC02-{pair}-I-SUCC", "LateStart"))
        for pair in ("A", "B", "C")
    )

    # Pair C deliberately creates an early gap between PRED and active SUCC.
    # An ordinary direct FS splice would report that gap as PRED FreeSlack.
    # Retaining the original edge to the inactive MID reports the gap to MID
    # instead (zero in this matrix). These are distinct observable contracts.
    c_pred = rows["RC02-C-I-PRED"]
    c_mid = rows["RC02-C-I-MID"]
    c_succ = rows["RC02-C-I-SUCC"]
    try:
        c_free = int(c_pred["FreeSlack"]) if c_pred["FreeSlack"] is not None else None
        c_total = int(c_pred["TotalSlack"]) if c_pred["TotalSlack"] is not None else None
    except (TypeError, ValueError):
        c_free = c_total = None
    c_direct_gap = slack_units_between(c_pred["EarlyFinish"], c_succ["EarlyStart"])
    c_inactive_edge_gap = slack_units_between(c_pred["EarlyFinish"], c_mid["EarlyStart"])
    c_direct_free = c_free is not None and c_free == c_direct_gap
    c_inactive_edge_free = c_free is not None and c_free == c_inactive_edge_gap
    c_drop = c_free is not None and c_total is not None and c_free == c_total

    # Paired effects are measured, not inferred from inactive coordinates alone.
    paired_effects = {
        f"pair_{pair.lower()}_forward_delta": slack_units_between(
            rows[f"RC02-{pair}-I-SUCC"]["Start"],
            rows[f"RC02-{pair}-A-SUCC"]["Start"],
        ) == (0 if pair == "C" else PAIR_HOURS[pair]["MID"] * 600)
        for pair in PAIR_HOURS
    } | {
        f"pair_{pair.lower()}_late_delta": slack_units_between(
            rows[f"RC02-{pair}-A-PRED"]["LateFinish"],
            rows[f"RC02-{pair}-I-PRED"]["LateFinish"],
        ) == PAIR_HOURS[pair]["MID"] * 600
        for pair in PAIR_HOURS
    }
    late_drop = all(
        eq(rows, (f"RC02-{pair}-I-PRED", "LateFinish"),
           ("RC02-FINISH-DRIVER", "Finish"))
        and not eq(rows, (f"RC02-{pair}-I-PRED", "LateFinish"),
                   (f"RC02-{pair}-I-SUCC", "LateStart"))
        for pair in PAIR_HOURS
    )
    date_passthrough = (
        controls_valid and all(paired_effects.values())
        and a_passthrough and b_passthrough and late_passthrough
    )
    direct_splice = date_passthrough and c_direct_free
    mixed_native = date_passthrough and c_inactive_edge_free and not c_direct_free
    dropped = controls_valid and a_drop and b_drop and c_drop and late_drop

    if direct_splice:
        verdict = "ZERO_DURATION_DATE_PASSTHROUGH_WITH_FREE_SLACK_MATCHING_ACTIVE_SUCCESSOR_GAP"
    elif mixed_native:
        verdict = "ZERO_DURATION_DATE_PASSTHROUGH_WITH_FREE_SLACK_MATCHING_INACTIVE_EDGE_GAP"
    elif dropped:
        verdict = "DROP_BOTH_ENDPOINT_EDGES_SUPPORTED"
    else:
        verdict = "NO_SINGLE_TESTED_RULE_ESTABLISHED"

    return {
        "verdict": verdict,
        "controls": {"valid": controls_valid, "checks": controls},
        "paired_effects": paired_effects,
        "components": {
            "date_semantic": (
                "ZERO_DURATION_FS_PASSTHROUGH_SUPPORTED"
                if date_passthrough else "NOT_ESTABLISHED"
            ),
            "free_slack_observation": (
                "MATCHES_INACTIVE_EDGE_GAP"
                if controls_valid and c_inactive_edge_free and not c_direct_free
                else (
                    "MATCHES_ACTIVE_SUCCESSOR_GAP"
                    if controls_valid and c_direct_free else "NOT_ESTABLISHED"
                )
            ),
        },
        "predicates": {
            "pair_a_drop": a_drop,
            "pair_a_date_passthrough": a_passthrough,
            "pair_b_drop": b_drop,
            "pair_b_date_passthrough": b_passthrough,
            "all_pairs_late_passthrough": late_passthrough,
            "all_pairs_late_drop_to_project_finish": late_drop,
            "pair_c_drop_free_equals_total": c_drop,
            "pair_c_free_equals_direct_active_successor_gap": c_direct_free,
            "pair_c_free_equals_original_inactive_edge_gap": c_inactive_edge_free,
        },
        "pair_c_slack_units": {
            "observed_free_slack": c_free,
            "total_slack": c_total,
            "direct_active_successor_gap": c_direct_gap,
            "original_inactive_edge_gap": c_inactive_edge_gap,
        },
        "validated_topology": {
            name: {
                "uid": rows[name]["UID"],
                "predecessor_links": rows[name]["predecessor_links"],
            }
            for name in sorted(EXPECTED)
        },
        "observations": {name: rows[name] for name in sorted(REQUIRED)},
    }


def analyze(payload: bytes) -> dict[str, object]:
    project, rows = parse(payload)
    return {
        "schema": SCHEMA,
        "native_return": {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
        "project": project,
        "classification": classify(rows),
    }


def serialize(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=False) + "\n"


def require_separate_output(source: Path, output: Path) -> None:
    if output.resolve() == source.resolve() or (
        output.exists() and output.samefile(source)
    ):
        raise SystemExit("output must be separate from native return (including file aliases)")


def write_candidate(source: Path, output: Path, payload: str) -> None:
    require_separate_output(source, output)
    # Replace the destination entry, never truncate an existing linked inode.
    # The second check also catches aliases introduced during analysis.
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
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--check", type=Path, help="verify exact committed analyzer output without writing")
    args = parser.parse_args()
    if args.output:
        require_separate_output(args.native_return, args.output)
    payload = serialize(analyze(args.native_return.read_bytes()))
    if args.check:
        if args.check.read_bytes() != payload.encode("utf-8"):
            raise SystemExit("committed evidence differs from exact analyzer output")
        print("committed evidence matches exact analyzer output")
    elif args.output:
        write_candidate(args.native_return, args.output, payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
