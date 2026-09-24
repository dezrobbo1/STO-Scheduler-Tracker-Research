#!/usr/bin/env python3
"""Classify the P1-G2 RC02 synthetic Microsoft Project native return.

This is evidence tooling only. It does not calculate a replacement schedule.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
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

FIELDS = (
    "UID", "ID", "Active", "Start", "Finish", "EarlyStart", "EarlyFinish",
    "LateStart", "LateFinish", "TotalSlack", "FreeSlack", "Critical",
)


def text(task: ET.Element, field: str) -> str | None:
    node = task.find(f"p:{field}", NS)
    return None if node is None else node.text


def read(path: Path) -> tuple[dict[str, str | None], dict[str, dict[str, object]]]:
    root = ET.parse(path).getroot()
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
        row: dict[str, object] = {field: text(task, field) for field in FIELDS}
        row["predecessor_uids"] = [
            link.findtext("p:PredecessorUID", default="", namespaces=NS)
            for link in task.findall("p:PredecessorLink", NS)
        ]
        rows[name] = row
    missing = sorted(REQUIRED - rows.keys())
    if missing:
        raise SystemExit("native return is missing matrix tasks: " + ", ".join(missing))
    wrong_active = sorted(
        name for name in REQUIRED
        if (rows[name]["Active"] == "0") != (name in INACTIVE)
    )
    if wrong_active:
        raise SystemExit("native return changed matrix Active flags: " + ", ".join(wrong_active))
    return project, rows


def eq(rows: dict[str, dict[str, object]], left: tuple[str, str], right: tuple[str, str]) -> bool:
    return rows[left[0]][left[1]] == rows[right[0]][right[1]]


def slack_units_between(start: object, finish: object) -> int | None:
    """Return MSPDI slack units (tenths of a minute) for this 24-hour matrix."""
    if not isinstance(start, str) or not isinstance(finish, str):
        return None
    return int((datetime.fromisoformat(finish) - datetime.fromisoformat(start)).total_seconds() / 6)


def classify(rows: dict[str, dict[str, object]]) -> dict[str, object]:
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

    date_passthrough = a_passthrough and b_passthrough and late_passthrough
    direct_splice = date_passthrough and c_direct_free
    mixed_native = date_passthrough and c_inactive_edge_free and not c_direct_free
    dropped = a_drop and b_drop and c_drop and not date_passthrough

    if direct_splice:
        verdict = "DIRECT_ZERO_LAG_FS_SPLICE_SUPPORTED"
    elif mixed_native:
        verdict = "ZERO_DURATION_DATE_PASSTHROUGH_WITH_INACTIVE_EDGE_FREE_SLACK"
    elif dropped:
        verdict = "DROP_BOTH_ENDPOINT_EDGES_SUPPORTED"
    else:
        verdict = "NO_SINGLE_TESTED_RULE_ESTABLISHED"

    return {
        "verdict": verdict,
        "components": {
            "date_semantic": (
                "ZERO_DURATION_FS_PASSTHROUGH_SUPPORTED"
                if date_passthrough else "NOT_ESTABLISHED"
            ),
            "free_slack_semantic": (
                "ORIGINAL_INACTIVE_EDGE_BOUND_SUPPORTED"
                if c_inactive_edge_free and not c_direct_free
                else (
                    "DIRECT_ACTIVE_SUCCESSOR_BOUND_SUPPORTED"
                    if c_direct_free else "NOT_ESTABLISHED"
                )
            ),
        },
        "predicates": {
            "pair_a_drop": a_drop,
            "pair_a_date_passthrough": a_passthrough,
            "pair_b_drop": b_drop,
            "pair_b_date_passthrough": b_passthrough,
            "all_pairs_late_passthrough": late_passthrough,
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
        "observations": {
            name: rows[name]
            for name in (
                "RC02-FINISH-DRIVER",
                "RC02-A-I-PRED", "RC02-A-I-MID", "RC02-A-I-SUCC",
                "RC02-B-I-PRED", "RC02-B-I-MID", "RC02-B-I-OTHER", "RC02-B-I-SUCC",
                "RC02-C-I-PRED", "RC02-C-I-MID", "RC02-C-I-OTHER", "RC02-C-I-SUCC",
            )
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("native_return", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project, rows = read(args.native_return)
    record = {
        "schema": "sto-p1-g2-rc02-native-matrix-v2",
        "project": project,
        "classification": classify(rows),
    }
    payload = json.dumps(record, indent=2, sort_keys=False) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
