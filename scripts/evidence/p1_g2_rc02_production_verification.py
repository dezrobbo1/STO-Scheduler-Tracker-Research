#!/usr/bin/env python3
"""Verify the bounded production RC02 inactive-boundary correction on BOILER.

This is post-correction evidence. It does not change scheduling semantics and it
never writes the customer schedule. The raw BOILER baseline remains external.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for import_root in (str(ROOT), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from scripts.evidence import p1_g2_baseline_diagnostics as baseline_diag
from scripts.evidence import p1_g2_rc02_boiler_counterfactual as prior_cf
from scripts.evidence.p1_g2_execution import (
    PRODUCTION_BASIS_PATHS,
    PRODUCTION_BASIS_PATH_TREE_SHA256,
    verify_production_basis,
)
from sto.core.engine import BACKWARD_PASS_PROFILE, CRITICALITY_PROFILE, VALIDATOR_PROFILE
from sto.core.engine.validate import validate_result

SCHEMA = "sto-p1-g2-rc02-production-verification-v1"
EVIDENCE_DATE = "2026-09-25"
PRODUCTION_COMMIT = "1982789f1c0aab83892dbac2f2d7b690ec9a85d6"
COUNTERFACTUAL_RESULT = ROOT / "docs/evidence/p1-g2-rc02-latest-successor-boiler-counterfactual-2026-09-25.json"
COUNTERFACTUAL_BYTES = 10_610
COUNTERFACTUAL_SHA256 = "439e8ef6a4e7f90b9866e76fa2a5f4a8bc4060e82b7ef7d7c144b19d0b24dc9c"
BASELINE_BYTES, BASELINE_SHA256 = baseline_diag.BASELINE_IDENTITY
FIELDS = tuple(baseline_diag.RESULT_FIELDS)
EXPECTED_BOUNDARIES = frozenset(
    {
        ("L0055", "L0052", "L0056"),
        ("L0055", "L0052", "L0060"),
        ("L0400", "L0388", "L0389"),
    }
)


class ProductionVerificationError(RuntimeError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_counterfactual() -> dict[str, object]:
    payload = COUNTERFACTUAL_RESULT.read_bytes()
    if len(payload) != COUNTERFACTUAL_BYTES or _sha256(payload) != COUNTERFACTUAL_SHA256:
        raise ProductionVerificationError("merged latest-successor counterfactual identity changed")
    record = json.loads(payload)
    if record.get("decision", {}).get("classification") != "RC02_LATEST_SUCCESSOR_COUNTERFACTUAL_SUPPORTED":
        raise ProductionVerificationError("merged counterfactual no longer authorizes the production correction")
    if record.get("acceptance", {}).get("counterfactual_success") is not True:
        raise ProductionVerificationError("merged counterfactual acceptance is not green")
    if record.get("inventory", {}).get("latest_successor_directional", {}).get("slots") != 147:
        raise ProductionVerificationError("merged counterfactual residual count changed")
    if record.get("rc02", {}).get("slots_after_latest_successor") != 0:
        raise ProductionVerificationError("merged counterfactual RC02 residual changed")
    return record


def _projection(engine: dict[str, tuple], leaf_by_source: dict[str, str]) -> tuple[bytes, str]:
    rows: list[list[object]] = []
    for source_uid, values in engine.items():
        row: list[object] = [leaf_by_source[source_uid]]
        for value in values:
            row.append(value.isoformat() if isinstance(value, datetime) else value)
        rows.append(row)
    rows.sort()
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return payload, _sha256(payload)


def _keyset_sha(keys: set[tuple[str, str]]) -> str:
    payload = json.dumps(
        sorted([list(key) for key in keys]),
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(payload)


def verify_current_production_basis() -> dict[str, object]:
    return verify_production_basis(
        repository_root=ROOT,
        declared_commit=PRODUCTION_COMMIT,
        production_paths=PRODUCTION_BASIS_PATHS,
        expected_path_tree_sha256=PRODUCTION_BASIS_PATH_TREE_SHA256,
    )


def build_record(baseline_path: Path) -> dict[str, object]:
    basis = verify_current_production_basis()
    counterfactual = _read_counterfactual()
    inventory = prior_cf.read_inventory()
    fixture = baseline_diag.read_verified_fixture(
        baseline_path,
        (BASELINE_BYTES, BASELINE_SHA256),
        "baseline",
    )
    schedule = baseline_diag._load(fixture.payload)
    calculation = baseline_diag._calculate(schedule)
    violations = validate_result(
        calculation.plan.network,
        calculation.forward,
        calculation.backward,
        calculation.floats,
    )
    if violations:
        raise ProductionVerificationError(
            "corrected production result does not validate: "
            + ", ".join(row.code for row in violations[:10])
        )

    observed = baseline_diag._observed(baseline_diag._activities(schedule))
    engine = baseline_diag._engine(schedule, calculation.result)
    leaf_by_uid, _, source_uid_by_leaf = prior_cf._leaf_maps(schedule)
    leaf_by_source = {source_uid: leaf for leaf, source_uid in source_uid_by_leaf.items()}
    fixed_rows = inventory["mismatches"]
    fixed_by_key = {(row["leaf_id"], row["field"]): row for row in fixed_rows}
    fixed_keys = set(fixed_by_key)
    current_keys = prior_cf._mismatch_keys(observed, engine, leaf_by_source)
    new_keys = current_keys - fixed_keys
    if new_keys:
        raise ProductionVerificationError("production correction introduced mismatch slots outside the fixed inventory")

    projection_payload, projection_sha = _projection(engine, leaf_by_source)
    keyset_sha = _keyset_sha(current_keys)

    current_summary = {
        "slots": len(current_keys),
        "leaves": len({leaf for leaf, _ in current_keys}),
        "by_field": dict(sorted(Counter(field for _, field in current_keys).items())),
        "by_group": dict(
            sorted(
                Counter(
                    fixed_by_key[key]["diagnostic_group"]
                    for key in current_keys
                ).items()
            )
        ),
    }
    expected_summary = counterfactual["inventory"]["latest_successor_directional"]
    if current_summary != expected_summary:
        raise ProductionVerificationError(
            "post-correction inventory summary differs from the merged PR #60 counterfactual"
        )

    movement_by_group: dict[str, Counter] = {}
    for key in sorted(fixed_keys):
        row = fixed_by_key[key]
        leaf_id, field = key
        source_uid = source_uid_by_leaf[leaf_id]
        index = FIELDS.index(field)
        before_delta = row["delta"].get("sto_minus_source")
        after_delta = prior_cf._delta(
            observed[source_uid][index],
            engine[source_uid][index],
        )
        status = prior_cf._movement(before_delta, after_delta)
        movement_by_group.setdefault(row["diagnostic_group"], Counter())[status] += 1
    movement_contract = {
        group: dict(sorted(counts.items()))
        for group, counts in sorted(movement_by_group.items())
    }
    if movement_contract != counterfactual["movement_by_original_group"]:
        raise ProductionVerificationError(
            "post-correction movement contract differs from the merged PR #60 counterfactual"
        )

    rc02_keys = {
        key for key in current_keys
        if fixed_by_key[key]["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY
    }
    groups = Counter(fixed_by_key[key]["diagnostic_group"] for key in current_keys)
    expected_groups = {"G2-RC01": 143, "G2-RC03": 3, "G2-RC04": 1}
    if dict(sorted(groups.items())) != expected_groups:
        raise ProductionVerificationError("post-correction root-cause inventory differs from the supported diagnostic")
    if rc02_keys:
        raise ProductionVerificationError("RC02 mismatches remain after the production correction")

    boundaries = frozenset(
        (
            leaf_by_uid[row.predecessor_uid],
            leaf_by_uid[row.inactive_boundary_uid],
            leaf_by_uid[row.successor_uid],
        )
        for row in calculation.plan.network.relationships
        if row.inactive_boundary_uid is not None
    )
    if boundaries != EXPECTED_BOUNDARIES:
        raise ProductionVerificationError(
            f"production inactive-boundary set changed: expected {sorted(EXPECTED_BOUNDARIES)}, got {sorted(boundaries)}"
        )

    remaining = []
    for key in sorted(current_keys):
        source = fixed_by_key[key]
        leaf_id, field = key
        source_uid = source_uid_by_leaf[leaf_id]
        index = FIELDS.index(field)
        delta = prior_cf._delta(observed[source_uid][index], engine[source_uid][index])
        remaining.append(
            {
                "leaf_id": leaf_id,
                "field": field,
                "diagnostic_group": source["diagnostic_group"],
                "dependency_role": source["dependency_role"],
                "sto_minus_source_seconds": delta,
            }
        )

    assumed = calculation.plan.assumed_by_code()
    if assumed.get("ACTIVITY_SUCCESSOR_OF_INACTIVE") != 2:
        raise ProductionVerificationError("unsupported inactive-boundary assumption count changed")

    return {
        "schema": SCHEMA,
        "evidence_date": EVIDENCE_DATE,
        "basis": {
            "fresh_main_before_correction": "26dc06b6352fd882fa32f6b60a03eddd9b2b3f68",
            "production_correction_commit": PRODUCTION_COMMIT,
            "production_path_tree_sha256": basis["path_tree_sha256"],
            "production_basis_verified": basis["verified_against_worktree"],
            "baseline": dict(fixture.identity),
            "fixed_inventory": {
                "bytes": prior_cf.INVENTORY_BYTES,
                "sha256": prior_cf.INVENTORY_SHA256,
                "schema": inventory["schema"],
            },
            "supported_counterfactual": {
                "bytes": COUNTERFACTUAL_BYTES,
                "sha256": COUNTERFACTUAL_SHA256,
                "classification": counterfactual["decision"]["classification"],
                "expected_inventory_summary": counterfactual["inventory"]["latest_successor_directional"],
                "expected_movement_by_original_group": counterfactual["movement_by_original_group"],
            },
        },
        "production_semantics": {
            "backward_profile": BACKWARD_PASS_PROFILE,
            "criticality_profile": CRITICALITY_PROFILE,
            "validator_profile": VALIDATOR_PROFILE,
            "inactive_boundary_relationships": [
                {
                    "active_predecessor_leaf_id": pred,
                    "inactive_leaf_id": inactive,
                    "active_successor_leaf_id": succ,
                }
                for pred, inactive, succ in sorted(boundaries)
            ],
            "unsupported_successor_assumption_count": assumed["ACTIVITY_SUCCESSOR_OF_INACTIVE"],
        },
        "verification": {
            "calculation_validator_clean": True,
            "production_projection_sha256": projection_sha,
            "production_remaining_keyset_sha256": keyset_sha,
            "inventory_summary_matches_supported_counterfactual": True,
            "movement_contract_matches_supported_counterfactual": True,
            "new_mismatch_slots": 0,
        },
        "inventory": {
            "before_slots": 422,
            "after_slots": len(current_keys),
            "after_leaves": len({leaf for leaf, _ in current_keys}),
            "closed_slots": 422 - len(current_keys),
            "by_group": dict(sorted(groups.items())),
            "rc02_slots_after": len(rc02_keys),
            "remaining_mismatches": remaining,
        },
        "decision": {
            "classification": "RC02_PRODUCTION_CORRECTION_VERIFIED",
            "rc02_closed_in_production": True,
            "p1_g2_closed": False,
            "p1_gate": "4/5 IN PROGRESS",
            "p2_started": False,
            "next_step": (
                "review the post-correction 147-slot inventory; G2-RC01 now owns 143 slots, "
                "G2-RC03 owns 3 and G2-RC04 owns 1 before any next production correction"
            ),
        },
    }


def serialize(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=False) + "\n"


def _separate(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve() or (
        destination.exists() and destination.samefile(source)
    ):
        raise SystemExit("output/check path must be separate from the private baseline")


def _write_atomic(source: Path, output: Path, payload: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        _separate(source, output)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.output:
        _separate(args.baseline, args.output)
    if args.check:
        _separate(args.baseline, args.check)
    payload = serialize(build_record(args.baseline))
    if args.check:
        if args.check.read_bytes() != payload.encode("utf-8"):
            raise SystemExit("committed RC02 production evidence differs from exact output")
        print("committed RC02 production evidence matches exact output")
    elif args.output:
        _write_atomic(args.baseline, args.output, payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
