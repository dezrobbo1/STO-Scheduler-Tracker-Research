#!/usr/bin/env python3
"""Verify the one-field RC02 Free-Slack sentinel native return."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.evidence import p1_g2_inactive_native_matrix as matrix
from scripts.evidence import p1_g2_inactive_native_matrix_generate as generate

SCHEMA = "sto-rc02-free-slack-sentinel-observation-v2"
SENTINEL_BYTES = 48326
SENTINEL_SHA256 = "454b536350761d56f57aea9ba47af3abff01e6afbb519c56601559596bcbf9a7"
ORIGINAL_NATIVE_BUILD = "16.0.20228.20188"
SEED = 12345
TARGET = "RC02-C-I-PRED"
REPLAY_COLUMNS = ("name",) + matrix.FIELDS + ("predecessor_links",)


def verify_generated_input() -> bytes:
    payload = generate.build_free_slack_sentinel_fixture()
    if len(payload) != SENTINEL_BYTES or hashlib.sha256(payload).hexdigest() != SENTINEL_SHA256:
        raise SystemExit("sentinel generator does not match pinned input identity")
    return payload


def pack_rows(rows: dict[str, dict[str, object]]) -> list[list[object]]:
    return [
        [
            name,
            *[rows[name][field] for field in matrix.FIELDS],
            rows[name]["predecessor_links"],
        ]
        for name in sorted(matrix.REQUIRED)
    ]


def unpack_rows(columns: list[str], packed: list[list[object]]) -> dict[str, dict[str, object]]:
    if tuple(columns) != REPLAY_COLUMNS:
        raise SystemExit("sentinel replay columns changed")
    rows: dict[str, dict[str, object]] = {}
    for values in packed:
        if len(values) != len(REPLAY_COLUMNS):
            raise SystemExit("sentinel replay row width changed")
        row = dict(zip(REPLAY_COLUMNS, values))
        name = str(row.pop("name"))
        row["predecessor_uids"] = [
            link["predecessor_uid"] for link in row["predecessor_links"]
        ]
        rows[name] = row
    matrix.validate_rows(rows)
    return rows


def replay(record: dict[str, object]) -> dict[str, object]:
    rows = unpack_rows(record["replay_columns"], record["replay_rows"])
    classification = matrix.classify(rows)
    pair_c = classification["pair_c_slack_units"]
    returned = int(rows[TARGET]["FreeSlack"])
    return {
        "expected_matrix_tasks": len(matrix.REQUIRED),
        "task_identity_and_zero_lag_fs_topology_preserved": True,
        "active_controls": classification["controls"],
        "date_semantic": classification["components"]["date_semantic"],
        "paired_effects": classification["paired_effects"],
        "pair_c": {
            "returned_free_slack": returned,
            "total_slack": pair_c["total_slack"],
            "direct_active_successor_gap": pair_c["direct_active_successor_gap"],
            "original_inactive_edge_gap": pair_c["original_inactive_edge_gap"],
        },
    }


def analyze(payload: bytes, *, owner_confirmed_opened_sentinel: bool) -> dict[str, object]:
    verify_generated_input()
    if not owner_confirmed_opened_sentinel:
        raise SystemExit(
            "owner confirmation that the pinned sentinel input was opened is required"
        )

    project, rows = matrix.parse(payload)
    classification = matrix.classify(rows)
    if (
        not classification["controls"]["valid"]
        or classification["components"]["date_semantic"]
        != "ZERO_DURATION_FS_PASSTHROUGH_SUPPORTED"
        or not all(classification["paired_effects"].values())
    ):
        raise SystemExit(
            "sentinel return does not reproduce the validated matrix controls/date shape"
        )

    packed = pack_rows(rows)
    pair_c = classification["pair_c_slack_units"]
    returned = int(rows[TARGET]["FreeSlack"])
    changed = returned != SEED
    matches_inactive = returned == pair_c["original_inactive_edge_gap"]
    matches_direct = returned == pair_c["direct_active_successor_gap"]
    diagnostic_authorized = changed and matches_inactive and not matches_direct

    record = {
        "schema": SCHEMA,
        "sentinel_input": {
            "bytes": SENTINEL_BYTES,
            "sha256": SENTINEL_SHA256,
            "task_uid": "20",
            "task_name": TARGET,
            "field": "FreeSlack",
            "seeded_value": SEED,
        },
        "native_return": {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "project": project,
        "input_lineage": {
            "owner_confirmed_opened_pinned_sentinel": True,
            "machine_proven_from_return_alone": False,
            "note": (
                "Owner supplied this returned XML in direct response to the pinned "
                "sentinel-run instructions; the return hash alone cannot prove which "
                "input was opened."
            ),
        },
        "same_build_as_original_native_run": (
            project["build_number"] == ORIGINAL_NATIVE_BUILD
        ),
        "original_native_build": ORIGINAL_NATIVE_BUILD,
        "replay_columns": list(REPLAY_COLUMNS),
        "replay_rows": packed,
        "conclusion": {
            "unchanged_sentinel_retention_ruled_out": changed,
            "returned_value_matches_original_inactive_edge_gap": matches_inactive,
            "returned_value_matches_direct_active_successor_gap": matches_direct,
            "general_free_slack_formula_established": False,
            "internal_project_mechanism_established": False,
            "diagnostic_boiler_counterfactual_authorized": diagnostic_authorized,
            "production_scheduler_change_authorized": False,
        },
    }
    record["validation"] = replay(record)
    return record


def serialize(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("native_return", type=Path)
    parser.add_argument("--confirm-opened-sentinel", action="store_true")
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()

    payload = serialize(
        analyze(
            args.native_return.read_bytes(),
            owner_confirmed_opened_sentinel=args.confirm_opened_sentinel,
        )
    )
    if args.check:
        if args.check.read_bytes() != payload.encode("utf-8"):
            raise SystemExit(
                "committed sentinel evidence differs from exact verifier output"
            )
        print("committed sentinel evidence matches exact verifier output")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
