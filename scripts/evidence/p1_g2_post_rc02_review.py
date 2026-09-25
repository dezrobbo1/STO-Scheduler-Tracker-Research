#!/usr/bin/env python3
"""Rebase the P1-G2 diagnosis on the verified post-RC02 production inventory."""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "sto-p1-g2-post-rc02-review-v1"
EVIDENCE_DATE = "2026-09-25"
REPOSITORY_BASE = "a4a401c42dcacfb3122467b017607aa6be1ee0e5"

HISTORICAL_PATH = ROOT / "docs/evidence/p1-g2-baseline-root-causes-2026-09-22.json"
HISTORICAL_BLOB_SHA = "f4eeb06bccb9681342db58ef84a06fa2c26742f8"
POST_RC02_PATH = ROOT / "docs/evidence/p1-g2-rc02-production-correction-2026-09-25.json"
POST_RC02_BLOB_SHA = "5ea13c477735bf52bd2ee2e07c62597036b09f2b"

RC01_ROOTS = (
    "L0070",
    "L0075",
    "L0080",
    "L0083",
    "L0084",
    "L0114",
    "L0127",
    "L0148",
    "L0157",
    "L0190",
)
RC03_ROOTS = ("L0407", "L0411")


class EvidenceError(ValueError):
    """The committed evidence no longer satisfies this review contract."""


def _git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _read_pinned(path: Path, expected_blob_sha: str) -> dict:
    payload = path.read_bytes()
    actual = _git_blob_sha(payload)
    if actual != expected_blob_sha:
        raise EvidenceError(
            f"{path.relative_to(ROOT)} blob changed: expected {expected_blob_sha}, got {actual}"
        )
    return json.loads(payload)


def load_inputs() -> tuple[dict, dict]:
    return (
        _read_pinned(HISTORICAL_PATH, HISTORICAL_BLOB_SHA),
        _read_pinned(POST_RC02_PATH, POST_RC02_BLOB_SHA),
    )


def _counts(rows: list[dict], key: str) -> dict[str, int]:
    return dict(sorted(Counter(row[key] for row in rows).items()))


def _leaf_count(rows: list[dict]) -> int:
    return len({row["leaf_id"] for row in rows})


def _group(historical: dict, group_id: str) -> dict:
    groups = {row["group_id"]: row for row in historical["root_cause_groups"]}
    try:
        return groups[group_id]
    except KeyError as exc:
        raise EvidenceError(f"historical evidence is missing {group_id}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def review_documents(historical: dict, post_rc02: dict) -> dict:
    _require(
        historical.get("schema") == "sto-p1-g2-baseline-root-causes-v3",
        "unexpected historical root-cause schema",
    )
    _require(
        post_rc02.get("schema") == "sto-p1-g2-rc02-production-verification-v1",
        "unexpected post-RC02 schema",
    )
    _require(
        post_rc02["decision"]["classification"] == "RC02_PRODUCTION_CORRECTION_VERIFIED"
        and post_rc02["decision"]["rc02_closed_in_production"] is True,
        "RC02 is not verified closed in the supplied production evidence",
    )

    rows = list(post_rc02["inventory"]["remaining_mismatches"])
    keys = {(row["leaf_id"], row["field"]) for row in rows}
    _require(len(rows) == 147 and len(keys) == 147, "current inventory is not 147 unique slots")
    _require(_leaf_count(rows) == 39, "current inventory is not 39 leaves")

    by_group = _counts(rows, "diagnostic_group")
    by_field = _counts(rows, "field")
    by_role = _counts(rows, "dependency_role")
    _require(
        by_group == {"G2-RC01": 143, "G2-RC03": 3, "G2-RC04": 1},
        f"unexpected post-RC02 group inventory: {by_group}",
    )
    _require(
        post_rc02["inventory"]["by_group"] == by_group
        and post_rc02["inventory"]["rc02_slots_after"] == 0,
        "post-RC02 summary does not reconcile with its slot inventory",
    )
    _require(
        not any(row["diagnostic_group"] == "G2-RC02" for row in rows),
        "RC02 residual unexpectedly remains",
    )

    rc01_rows = [row for row in rows if row["diagnostic_group"] == "G2-RC01"]
    rc01_first = {
        row["leaf_id"]
        for row in rc01_rows
        if row["dependency_role"] == "FIRST_DIVERGENCE"
    }
    rc01_historical = _group(historical, "G2-RC01")
    _require(
        set(rc01_historical["root_leaf_ids"]) == set(RC01_ROOTS) == rc01_first,
        "the current RC01 first-divergence roots no longer match the historical diagnosis",
    )
    _require(
        rc01_historical["causal_confidence"] == "STRONG_CANDIDATE"
        and rc01_historical["replacement_semantics_status"] == "NOT_ESTABLISHED"
        and rc01_historical["production_correction_justified"] is False,
        "historical RC01 evidence no longer carries the expected bounded status",
    )

    for leaf_id in RC01_ROOTS:
        activity = historical["activities"][leaf_id]
        expected = {
            "disposition": "ASSUMED_LABELLED",
            "progress_state": "not_started",
            "activity_kind": "task",
            "active": True,
            "manual": False,
            "planned_duration_class": "positive_working",
            "remaining_duration_class": "positive_working",
            "calendar_class": "resource_calendar_union",
            "resource_calendar_count": 2,
            "assignment_count": 2,
            "constraint_type": "asap",
            "incoming_relationship_types": ["FS"],
            "outgoing_relationship_types": ["FS"],
            "incoming_lag_classes": ["zero"],
            "outgoing_lag_classes": ["zero"],
            "assumption_codes": ["ACTIVITY_RESOURCE_CALENDARS_UNITED"],
        }
        observed = {key: activity.get(key) for key in expected}
        _require(observed == expected, f"RC01 root shape drifted for {leaf_id}: {observed}")

    movement = post_rc02["basis"]["supported_counterfactual"][
        "expected_movement_by_original_group"
    ]["G2-RC01"]
    _require(
        movement == {"closed": 17, "improved": 11, "unchanged": 132},
        "RC01 movement contract differs from the merged RC02 evidence",
    )
    _require(
        rc01_historical["field_slot_count"] == 160 and len(rc01_rows) == 143,
        "RC01 before/after slot accounting is inconsistent",
    )

    rc03_rows = [row for row in rows if row["diagnostic_group"] == "G2-RC03"]
    rc03_historical = _group(historical, "G2-RC03")
    _require(
        rc03_historical["causal_confidence"] == "PROVEN"
        and set(rc03_historical["root_leaf_ids"]) == set(RC03_ROOTS)
        and {row["leaf_id"] for row in rc03_rows} == set(RC03_ROOTS),
        "RC03 no longer matches the proven elapsed-duration float diagnosis",
    )

    rc04_rows = [row for row in rows if row["diagnostic_group"] == "G2-RC04"]
    rc04_historical = _group(historical, "G2-RC04")
    _require(len(rc04_rows) == 1, "RC04 is no longer a one-slot residual")
    _require(
        rc04_historical["evidence"]["coordinate_root_groups"]
        == ["G2-RC01", "G2-RC02"],
        "historical RC04 parentage changed",
    )

    return {
        "schema": SCHEMA,
        "evidence_date": EVIDENCE_DATE,
        "basis": {
            "repository_base": REPOSITORY_BASE,
            "historical_root_cause_record": {
                "path": str(HISTORICAL_PATH.relative_to(ROOT)),
                "git_blob_sha": HISTORICAL_BLOB_SHA,
                "schema": historical["schema"],
            },
            "post_rc02_production_record": {
                "path": str(POST_RC02_PATH.relative_to(ROOT)),
                "git_blob_sha": POST_RC02_BLOB_SHA,
                "schema": post_rc02["schema"],
                "production_correction_commit": post_rc02["basis"]["production_correction_commit"],
            },
        },
        "current_inventory": {
            "slots": len(rows),
            "leaves": _leaf_count(rows),
            "by_group": by_group,
            "by_field": by_field,
            "by_role": by_role,
            "rc02_slots": 0,
        },
        "rc01_review": {
            "classification": "REVALIDATED_STRONG_CANDIDATE",
            "historical_name": rc01_historical["name"],
            "current_slots": len(rc01_rows),
            "current_leaves": _leaf_count(rc01_rows),
            "current_by_field": _counts(rc01_rows, "field"),
            "current_by_role": _counts(rc01_rows, "dependency_role"),
            "root_leaf_count": len(RC01_ROOTS),
            "root_leaf_ids": list(RC01_ROOTS),
            "root_shape": {
                "all_roots_match": True,
                "assignment_count": 2,
                "resource_calendar_count": 2,
                "calendar_class": "resource_calendar_union",
                "assumption_code": "ACTIVITY_RESOURCE_CALENDARS_UNITED",
            },
            "original_slots": rc01_historical["field_slot_count"],
            "movement_during_rc02_correction": movement,
            "causal_confidence": "STRONG_CANDIDATE",
            "replacement_semantics_status": "NOT_ESTABLISHED",
            "boiler_counterfactual_authorized": False,
            "production_correction_authorized": False,
        },
        "rc03_review": {
            "classification": "PROVEN_ORIGIN_REMAINS",
            "historical_name": rc03_historical["name"],
            "current_slots": len(rc03_rows),
            "current_leaves": _leaf_count(rc03_rows),
            "root_leaf_ids": list(RC03_ROOTS),
            "causal_confidence": "PROVEN",
            "replacement_semantics_status": "NOT_ESTABLISHED",
            "production_correction_authorized": False,
        },
        "rc04_review": {
            "classification": "HISTORICAL_COMPOUND_LABEL_REQUIRES_RECLASSIFICATION",
            "current_slots": 1,
            "current_leaf_ids": sorted({row["leaf_id"] for row in rc04_rows}),
            "historical_parent_groups": ["G2-RC01", "G2-RC02"],
            "current_rc02_slots": 0,
            "independent_fix_authorized": False,
            "reason": (
                "the historical one-slot compound diagnosis depended on RC01 and RC02; "
                "RC02 now has zero residual slots, so the old parent decomposition is not "
                "a current production explanation and must be reassessed after RC01"
            ),
        },
        "next_experiment": {
            "id": "P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1",
            "status": "PREDECLARED_NOT_RUN",
            "purpose": (
                "distinguish the current union-of-resource-calendars approximation from "
                "assignment-level scheduling whose task span is the envelope of the "
                "calculated assignment spans"
            ),
            "synthetic_only": True,
            "cases": [
                {
                    "id": "A",
                    "shape": "two assignments on deliberately separated resource calendars",
                    "discriminator": (
                        "assignment-level scheduling must create a task span with a calendar gap "
                        "that a union-calendar duration placement cannot reproduce"
                    ),
                },
                {
                    "id": "B",
                    "shape": "case A with assignment declaration order reversed",
                    "discriminator": "same calculated task and assignment coordinates as A",
                },
                {
                    "id": "C",
                    "shape": "two assignments whose resource calendars overlap over the complete work window",
                    "discriminator": "control for the no-gap case",
                },
                {
                    "id": "D",
                    "shape": "single resource assignment",
                    "discriminator": "control for the already-supported one-resource calendar rule",
                },
            ],
            "required_return_observations": [
                "task Start, Finish and Duration",
                "each assignment Start, Finish, Work and Units",
                "resource identity and resource-calendar identity",
                "task type, effort-driven flag and IgnoreResourceCalendar",
                "Microsoft Project build number",
            ],
            "acceptance_rule": [
                "each assignment span is compatible with its own resource calendar",
                "for every two-assignment case task Start equals the earliest assignment Start",
                "for every two-assignment case task Finish equals the latest assignment Finish",
                "reversing assignment declaration order does not change the result",
                "the single-resource control remains consistent with the existing resource-calendar rule",
                "the separated-calendar case differs from the current union-calendar placement",
            ],
            "stopping_rule": (
                "only a return satisfying every acceptance condition authorizes a separate "
                "diagnostic-only BOILER RC01 counterfactual; it does not authorize a production change"
            ),
            "native_return_required": True,
            "boiler_counterfactual_authorized": False,
            "production_correction_authorized": False,
        },
        "decision": {
            "p1_g2_closed": False,
            "p1_gate": "4/5 IN PROGRESS",
            "p2_started": False,
            "next_action": (
                "build and run the predeclared synthetic RC01 assignment-envelope native matrix; "
                "do not change production scheduling semantics yet"
            ),
        },
    }


def build_record() -> dict:
    historical, post_rc02 = load_inputs()
    return review_documents(historical, post_rc02)


def serialize(record: dict) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = serialize(build_record())
    if args.check is not None:
        if args.check.read_text(encoding="utf-8") != payload:
            print(f"{args.check} does not match the current post-RC02 review", file=sys.stderr)
            return 1
        return 0
    if args.output is not None:
        args.output.write_text(payload, encoding="utf-8")
        return 0
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
