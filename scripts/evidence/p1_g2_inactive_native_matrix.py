#!/usr/bin/env python3
"""Classify the P1-G2 RC02 synthetic Microsoft Project native return.

This is evidence tooling only. It does not calculate a replacement schedule.
"""
from __future__ import annotations

import argparse
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


def classify(rows: dict[str, dict[str, object]]) -> dict[str, object]:
    # Pair A distinguishes "drop both endpoint edges" from a direct FS splice.
    a_drop = eq(rows, ("RC02-A-I-SUCC", "Start"), ("RC02-FINISH-DRIVER", "Start"))
    a_splice = eq(rows, ("RC02-A-I-SUCC", "Start"), ("RC02-A-I-PRED", "Finish"))

    # Pair B adds an ordinary active predecessor. OTHER finishes first, so a
    # spliced PRED->SUCC FS edge must drive; a dropped inactive path cannot.
    b_drop = eq(rows, ("RC02-B-I-SUCC", "Start"), ("RC02-B-I-OTHER", "Finish"))
    b_splice = eq(rows, ("RC02-B-I-SUCC", "Start"), ("RC02-B-I-PRED", "Finish"))

    # Pair C makes OTHER finish after PRED. Forward placement is therefore the
    # same under both hypotheses. Free slack on PRED is the discriminator:
    # with no effective successor it equals total slack; with an inferred edge
    # it is bounded before total slack.
    c_free = rows["RC02-C-I-PRED"]["FreeSlack"]
    c_total = rows["RC02-C-I-PRED"]["TotalSlack"]
    c_drop = c_free is not None and c_free == c_total
    try:
        c_splice = c_free is not None and c_total is not None and int(c_free) < int(c_total)
    except ValueError:
        c_splice = False

    direct = a_splice and b_splice and c_splice
    dropped = a_drop and b_drop and c_drop
    if direct and not dropped:
        verdict = "DIRECT_ZERO_LAG_FS_SPLICE_SUPPORTED"
    elif dropped and not direct:
        verdict = "DROP_BOTH_ENDPOINT_EDGES_SUPPORTED"
    else:
        verdict = "NO_SINGLE_TESTED_RULE_ESTABLISHED"

    return {
        "verdict": verdict,
        "predicates": {
            "pair_a_drop": a_drop,
            "pair_a_direct_fs_splice": a_splice,
            "pair_b_drop": b_drop,
            "pair_b_direct_fs_splice": b_splice,
            "pair_c_drop_free_equals_total": c_drop,
            "pair_c_direct_fs_splice_free_less_than_total": c_splice,
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
        "schema": "sto-p1-g2-rc02-native-matrix-v1",
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
