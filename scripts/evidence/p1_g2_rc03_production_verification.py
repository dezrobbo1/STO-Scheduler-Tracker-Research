#!/usr/bin/env python3
"""Pin the exact RC03 production movement without rewriting historical evidence.

The before coordinate and unaffected-output digests were measured from the
detached PR #65 merge commit on the exact immutable BOILER source.  They cover
every calculated leaf, not only the two elapsed-duration roots.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from scripts.evidence import p1_g2_baseline_diagnostics as baseline
from scripts.evidence import p1_g2_post_rc02_review as safe
from scripts.evidence import p1_g2_rc02_boiler_counterfactual as keys
from sto.core.engine.criticality import CRITICALITY_PROFILE
from sto.core.engine.result import RESULT_PROFILE
from sto.core.engine.validate import VALIDATOR_PROFILE, validate_result
from tests.controlled_native_progress_evidence import classify_controlled_transition
from tests.real_fixture_guard import verify_available
from tests import test_controlled_native_progress_boiler as controlled

SCHEMA = "sto-p1-g2-rc03-production-verification-v1"
STARTING_MAIN = "4d981101b3ef0c238646ed45380f8ba34afd0cae"
BOILER_BYTES = 3_361_935
BOILER_SHA = "e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70"
PR65_RECORD = ROOT / "docs/evidence/p1-g2-rc01-production-correction-2026-09-28.json"
PR65_SHA = "9781ce3e02ff429ee4f3f46ff8cb1f7e4b7f7decea66a8dc179e20a6bed07c75"
NATIVE_BYTES = 3_362_778
NATIVE_SHA = "6e0e5321ecadf4b8d9e96685968112803975737a61444104b45ae8cfa522df66"
CHANGED = {("L0407", "free_float"), ("L0407", "total_float"),
           ("L0411", "total_float")}
BEFORE = {("L0407", "free_float"): 0, ("L0407", "total_float"): 86400,
          ("L0411", "total_float"): 70200}
SOURCE = {("L0407", "free_float"): 7200, ("L0407", "total_float"): 387000,
          ("L0411", "total_float"): 361800}
# Calculated on the exact BOILER under STARTING_MAIN, across all 451 scheduled
# leaves, in pseudonym order.  The stable digest excludes only CHANGED.
COORDINATES_SHA = "e18c1f8d02c3fd224b1cdc22b583d2530f7770da2040935e50c613ab633e0c9d"
OTHER_OUTPUTS_SHA = "8743a9c873ce9695b25b0b94d7dc8c0472fa37678e8cef9770f29ee75ecb992b"
OLD_NETWORK = "7a9849047f619d1c02186379a363c44f4020e666371fe113caf7d48c9bf6c315"
OLD_FLOAT_RESULT = "26c8cd9988587e06b33776e5426aa822abf94c21d4b0d4a98c894ebbe5d3faf8"


class VerificationError(ValueError):
    """The exact controlled RC03 evidence contract did not hold."""


def stable_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def wire(value):
    return value.isoformat() if isinstance(value, datetime) else value


def build_record(source: Path, native: Path) -> dict:
    payload = source.read_bytes()
    if len(payload) != BOILER_BYTES or hashlib.sha256(payload).hexdigest() != BOILER_SHA:
        raise VerificationError("exact controlled BOILER baseline identity differs")
    native_payload = native.read_bytes()
    if (len(native_payload) != NATIVE_BYTES
        or hashlib.sha256(native_payload).hexdigest() != NATIVE_SHA):
        raise VerificationError("exact UID227 controlled native identity differs")
    verify_available({"boiler_before": source, "controlled_native_repeat": native})
    predecessor = PR65_RECORD.read_bytes()
    if hashlib.sha256(predecessor).hexdigest() != PR65_SHA:
        raise VerificationError("immutable PR #65 evidence identity changed")
    previous = json.loads(predecessor)
    if (previous["after"]["slots"] != 3
        or {tuple(key) for key in previous["after"]["remaining_keys"]} != CHANGED
        or previous["movement"]["new_keys"] or previous["movement"]["worsened_keys"]
        or previous["validator"]["violations"]):
        raise VerificationError("PR #65 predecessor result is not the exact three keys")

    schedule = baseline._load(payload)
    calculation = baseline._calculate(schedule)
    leaf_by_uid, _, source_by_leaf = keys._leaf_maps(schedule)
    source_to_leaf = {source_uid: leaf for leaf, source_uid in source_by_leaf.items()}
    calculated = baseline._engine(schedule, calculation.result)
    observed = baseline._observed(baseline._activities(schedule))
    rows = {leaf: calculated[src] for leaf, src in source_by_leaf.items()
            if src in calculated}
    excluded = {row.uid for row in calculation.plan.excluded if row.kind == "activity"}
    scheduled = set(calculation.plan.network.activity_by_uid())
    if (len(rows) != 451 or len(excluded) != 9 or scheduled & excluded
        or scheduled | excluded != {row.uid for row in schedule.activities}):
        raise VerificationError("controlled scheduled/excluded partition changed")
    coordinates = {leaf: [wire(value) for value in values[:6]]
                   for leaf, values in rows.items()}
    stable = {leaf: {field: wire(values[index])
                     for index, field in enumerate(baseline.RESULT_FIELDS)
                     if (leaf, field) not in CHANGED}
              for leaf, values in rows.items()}
    if stable_sha(coordinates) != COORDINATES_SHA:
        raise VerificationError("one or more BOILER scheduling coordinates moved")
    if stable_sha(stable) != OTHER_OUTPUTS_SHA:
        raise VerificationError("a BOILER output beyond the three RC03 fields moved")
    elapsed = {leaf_by_uid[row.uid] for row in calculation.plan.network.activities
               if row.float_basis == "elapsed"}
    if elapsed != {"L0407", "L0411"}:
        raise VerificationError("bounded elapsed-float BOILER eligibility changed")
    assumptions = {leaf_by_uid[row.uid] for row in calculation.plan.assumed
                   if row.kind == "activity" and row.code == "ACTIVITY_DURATION_ELAPSED"}
    if not elapsed <= assumptions:
        raise VerificationError("elapsed placement assumption disappeared")

    mismatches = keys._mismatch_keys(observed, calculated, source_to_leaf)
    if mismatches:
        raise VerificationError("RC03 production did not reach zero BOILER mismatch keys: "
                                + repr(sorted(mismatches)))
    movement = {}
    for leaf, field in sorted(CHANGED):
        index = baseline.RESULT_FIELDS.index(field)
        actual, source_value = rows[leaf][index], observed[source_by_leaf[leaf]][index]
        if actual != SOURCE[leaf, field] or source_value != SOURCE[leaf, field]:
            raise VerificationError(f"RC03 {leaf}/{field} did not reach its pinned native value")
        movement.setdefault(leaf, {})[field] = {
            "before": BEFORE[leaf, field], "after": actual,
            "source": source_value, "delta_seconds": actual - BEFORE[leaf, field],
        }
    violations = validate_result(calculation.plan.network, calculation.forward,
                                 calculation.backward, calculation.floats)
    if violations:
        raise VerificationError("independent validator violations: "
                                + repr([row.code for row in violations[:10]]))

    # Re-run the original predeclared 4,140-field classifier, including the
    # controlled synthetic input and Project-return recalculation.  Only the
    # actual measured output may close the gate.
    returned = controlled._load(native)
    baseline_rows = controlled._activities(schedule)
    native_rows = controlled._activities(returned)
    if (returned.snapshots[0].application_version != "16.0.20228.20186"
        or set(baseline_rows) != set(native_rows)
        or controlled._project_signature(schedule) != controlled._project_signature(returned)
        or controlled._relationship_signature(schedule) != controlled._relationship_signature(returned)
        or controlled._calendar_fingerprint(schedule) != controlled._calendar_fingerprint(returned)
        or controlled._resource_fingerprint(schedule) != controlled._resource_fingerprint(returned)
        or controlled._wbs_fingerprint(schedule) != controlled._wbs_fingerprint(returned)):
        raise VerificationError("UID227 native input/build or topology differs")
    selected = baseline_rows["227"]
    moved = replace(selected, actual_start=datetime.fromisoformat("2026-09-14T11:00:00"),
                    remaining_duration=replace(selected.remaining_duration, seconds=14400))
    controlled_schedule = replace(
        schedule, activities=tuple(moved if row.uid == selected.uid else row
                                   for row in schedule.activities))
    _, _, controlled_result = controlled._calculate(controlled_schedule)
    native_calculation = baseline._calculate(returned)
    native_violations = validate_result(native_calculation.plan.network,
                                        native_calculation.forward,
                                        native_calculation.backward,
                                        native_calculation.floats)
    if native_violations:
        raise VerificationError("native recalculation validator violations")
    summary = classify_controlled_transition(
        controlled._observed(baseline_rows), controlled._observed(native_rows),
        controlled._engine(schedule, calculation.result),
        controlled._engine(schedule, controlled_result),
        controlled._engine(returned, native_calculation.result),
        controlled._excluded(calculation.plan, schedule),
    )
    classifications = dict(summary.classifications)
    if (summary.field_slots != 4140 or summary.common_rows != 460
        or summary.added_rows or summary.removed_rows
        or classifications != {"UNCHANGED": 4016, "ENGINE_NATIVE_AGREEMENT": 43,
                               "EXPLICIT_EXCLUSION": 81}
        or summary.baseline_mismatches or summary.unexplained
        or summary.unexpected_transition_count != 0):
        raise VerificationError("controlled G2/G3 field classifier did not reach exact gate")
    if source.read_bytes() != payload:
        raise VerificationError("BOILER input bytes changed during verification")
    if native.read_bytes() != native_payload:
        raise VerificationError("UID227 return bytes changed during verification")
    return {
        "schema": SCHEMA,
        "starting_main": STARTING_MAIN,
        "pr65_merge_commit": STARTING_MAIN,
        "predecessor_record_sha256": PR65_SHA,
        "boiler": {"bytes": len(payload), "sha256": BOILER_SHA},
        "before": {"slots": 3, "leaves": 2,
                   "keys": [list(key) for key in sorted(CHANGED)]},
        "after": {"slots": len(mismatches), "unresolved_leaves": 0,
                  "keys": [list(key) for key in sorted(mismatches)]},
        "movement": {"changed_slots": movement, "new_keys": [],
                     "worsened_keys": [], "other_output_slots_changed": 0},
        "projection": {"scheduled": len(rows), "excluded": len(excluded),
                       "coordinates_before_and_after_sha256": COORDINATES_SHA,
                       "other_outputs_before_and_after_sha256": OTHER_OUTPUTS_SHA},
        "eligibility": {"elapsed_float_leaves": sorted(elapsed),
                        "other_elapsed_leaves_promoted": 0,
                        "elapsed_placement_assumption_retained": True},
        "identities": {"network_before": OLD_NETWORK,
                       "network_after": calculation.plan.network.fingerprint(),
                       "float_result_before": OLD_FLOAT_RESULT,
                       "float_result_after": calculation.floats.fingerprint,
                       "criticality_profile": {"before": "sto-criticality-v7",
                                               "after": CRITICALITY_PROFILE},
                       "validator_profile": {"before": "sto-validator-v5",
                                             "after": VALIDATOR_PROFILE},
                       "result_profile": {"before": "sto-result-v4", "after": RESULT_PROFILE}},
        "validator": {"profile": VALIDATOR_PROFILE, "violations": []},
        "controlled_uid227": {"bytes": len(native_payload), "sha256": NATIVE_SHA,
                              "build": returned.snapshots[0].application_version,
                              "common_leaves": summary.common_rows,
                              "field_slots": summary.field_slots,
                              "classifications": classifications,
                              "baseline_mismatches": len(summary.baseline_mismatches),
                              "unexplained": len(summary.unexplained),
                              "added_rows": summary.added_rows,
                              "removed_rows": summary.removed_rows,
                              "unexpected_transition_differences": summary.unexpected_transition_count,
                              "g3_native_changed_reconciled": classifications["ENGINE_NATIVE_AGREEMENT"]},
        "decision": {"boiler_rc03_closed": True, "p1_g2_met": True,
                     "p1_gate": "5/5 PASS", "p2_started": False},
    }


def protected(source: Path, native: Path) -> dict[str, Path]:
    return {"BOILER baseline": source, "UID227 native return": native,
            **{f"evidence:{p.name}": p
            for p in PR65_RECORD.parent.iterdir() if p.is_file()}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("boiler", type=Path)
    parser.add_argument("native", type=Path)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--check", type=Path)
    destination.add_argument("--output", type=Path)
    args = parser.parse_args()
    sources = protected(args.boiler, args.native)
    if args.output is not None:
        safe.refuse_output_alias(args.output, sources)
    serialized = json.dumps(build_record(args.boiler, args.native), sort_keys=True, indent=2) + "\n"
    if args.check is not None:
        if args.check.read_bytes() != serialized.encode():
            raise VerificationError("committed RC03 evidence differs")
    else:
        safe.write_output_safely(args.output, serialized, sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
