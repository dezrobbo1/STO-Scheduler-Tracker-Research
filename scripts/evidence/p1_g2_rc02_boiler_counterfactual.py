#!/usr/bin/env python3
"""Run the bounded P1-G2 RC02 BOILER diagnostic counterfactual.

This evidence tool does not change production scheduler semantics. It verifies
that current production still reproduces the fixed 422-slot baseline inventory,
then overlays one diagnostic relationship transform on the in-memory network:
for each exact one-hop active -> inactive -> active zero-lag FS boundary, add a
zero-lag active -> active FS edge so the inactive duration does not participate
in date placement. The imported Schedule and production build_plan result are
never mutated.

The synthetic native matrix established the one-successor date-pass-through
shape. Applying the same splice across a real-file fan-out is intentionally a
counterfactual, not an implementation claim. The result determines whether the
next step is a production correction or another native experiment.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
from uuid import NAMESPACE_URL, UUID, uuid5

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for import_root in (str(ROOT), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from scripts.evidence import p1_g2_baseline_diagnostics as baseline_diag
from sto.core.engine import backward_pass, float_analysis, forward_pass
from sto.core.engine.criticality import signed_working
from sto.core.engine.network import Network, PlannedRelationship
from sto.core.model.enums import RelationshipType

SCHEMA = "sto-p1-g2-rc02-boiler-counterfactual-v1"
EVIDENCE_DATE = "2026-09-24"
MAIN_BASIS = "43333a871916368359eb705e9080a9522e12db2b"
PRODUCTION_SOURCE_DIGEST = "22e8bf15ed5181067b8294a0f6cb6b1b46d1612c216e8d11985284f5759ecac5"
INVENTORY_PATH = ROOT / "docs/evidence/p1-g2-baseline-root-causes-2026-09-22.json"
INVENTORY_BYTES = 376_346
INVENTORY_SHA256 = "2408fc99f282e9c600d3821b3c926f7deafa8c05044c7fec9a5f08b2b656bf63"
BASELINE_BYTES, BASELINE_SHA256 = baseline_diag.BASELINE_IDENTITY
FIELDS = tuple(baseline_diag.RESULT_FIELDS)
EXPECTED_SPLICES = frozenset(
    {
        ("L0055", "L0052", "L0056"),
        ("L0055", "L0052", "L0060"),
        ("L0400", "L0388", "L0389"),
    }
)


class CounterfactualError(RuntimeError):
    """The fixed evidence contract no longer holds."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def production_source_digest(root: Path = ROOT) -> str:
    paths: list[Path] = []
    for directory in (root / "src/sto/core", root / "src/sto/legacy"):
        paths.extend(directory.rglob("*.py"))
    paths.extend(
        (
            root / "scripts/evidence/p1_g2_baseline_diagnostics.py",
            root / "tests/controlled_native_progress_evidence.py",
        )
    )
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda row: row.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def read_inventory(path: Path = INVENTORY_PATH) -> dict[str, object]:
    payload = path.read_bytes()
    if len(payload) != INVENTORY_BYTES or _sha256(payload) != INVENTORY_SHA256:
        raise CounterfactualError("fixed P1-G2 inventory identity changed")
    record = json.loads(payload)
    if record.get("schema") != "sto-p1-g2-baseline-root-causes-v3":
        raise CounterfactualError("unexpected P1-G2 inventory schema")
    mismatches = record.get("mismatches")
    if not isinstance(mismatches, list) or len(mismatches) != 422:
        raise CounterfactualError("fixed P1-G2 inventory is not 422 slots")
    return record


def _zero_lag_fs(relationship) -> bool:
    if relationship.type is not RelationshipType.FS:
        return False
    if relationship.lag is None:
        return True
    return relationship.lag.seconds == 0 and not relationship.lag.elapsed


def _leaf_maps(schedule) -> tuple[dict[UUID, str], dict[str, UUID], dict[str, str]]:
    ordered = sorted(schedule.activities, key=lambda row: int(baseline_diag._source_uid(row)))
    leaf_by_uid = {row.uid: f"L{index:04d}" for index, row in enumerate(ordered, 1)}
    uid_by_leaf = {leaf: uid for uid, leaf in leaf_by_uid.items()}
    source_uid_by_leaf = {
        leaf_by_uid[row.uid]: baseline_diag._source_uid(row) for row in ordered
    }
    return leaf_by_uid, uid_by_leaf, source_uid_by_leaf


def diagnostic_splices(schedule, production_network: Network) -> tuple[tuple[PlannedRelationship, ...], tuple[dict[str, object], ...]]:
    scheduled = set(production_network.activity_by_uid())
    leaf_by_uid, _, _ = _leaf_maps(schedule)
    incoming: dict[UUID, list] = {row.uid: [] for row in schedule.activities}
    outgoing: dict[UUID, list] = {row.uid: [] for row in schedule.activities}
    for relationship in schedule.relationships:
        incoming.setdefault(relationship.successor_uid, []).append(relationship)
        outgoing.setdefault(relationship.predecessor_uid, []).append(relationship)

    existing = {
        (row.predecessor_uid, row.successor_uid, row.type, row.lag)
        for row in production_network.relationships
    }
    splices: list[PlannedRelationship] = []
    evidence: list[dict[str, object]] = []
    for inactive in schedule.activities:
        if inactive.active:
            continue
        predecessors = [
            row for row in incoming.get(inactive.uid, ())
            if row.predecessor_uid in scheduled and _zero_lag_fs(row)
        ]
        successors = [
            row for row in outgoing.get(inactive.uid, ())
            if row.successor_uid in scheduled and _zero_lag_fs(row)
        ]
        if not predecessors or not successors:
            continue
        for predecessor in predecessors:
            for successor in successors:
                key = (
                    predecessor.predecessor_uid,
                    successor.successor_uid,
                    RelationshipType.FS,
                    0,
                )
                if key in existing:
                    raise CounterfactualError("diagnostic splice already exists in production network")
                uid = uuid5(
                    NAMESPACE_URL,
                    "sto:diagnostic:p1-g2-rc02:"
                    f"{predecessor.predecessor_uid}:{inactive.uid}:{successor.successor_uid}",
                )
                splices.append(
                    PlannedRelationship(
                        uid=uid,
                        predecessor_uid=predecessor.predecessor_uid,
                        successor_uid=successor.successor_uid,
                        type=RelationshipType.FS,
                        lag=0,
                        lag_calendar=None,
                    )
                )
                evidence.append(
                    {
                        "active_predecessor_leaf_id": leaf_by_uid[predecessor.predecessor_uid],
                        "inactive_leaf_id": leaf_by_uid[inactive.uid],
                        "active_successor_leaf_id": leaf_by_uid[successor.successor_uid],
                    }
                )
                existing.add(key)

    actual = frozenset(
        (
            row["active_predecessor_leaf_id"],
            row["inactive_leaf_id"],
            row["active_successor_leaf_id"],
        )
        for row in evidence
    )
    if actual != EXPECTED_SPLICES:
        raise CounterfactualError(
            f"bounded BOILER splice set changed: expected {sorted(EXPECTED_SPLICES)}, got {sorted(actual)}"
        )
    return tuple(splices), tuple(sorted(evidence, key=lambda row: tuple(row.values())))


def _run_diagnostic(plan, relationships: tuple[PlannedRelationship, ...]):
    network = replace(
        plan.network,
        relationships=plan.network.relationships + relationships,
    )
    early = forward_pass(
        network,
        snap_milestones=plan.snap_milestones,
        progress_policy=plan.progress_policy,
    )
    late = backward_pass(
        network,
        early,
        snap_milestones=plan.snap_milestones,
        progress_policy=plan.progress_policy,
    )
    floats = float_analysis(
        network,
        early,
        late,
        threshold=plan.critical_float_threshold,
    )
    early_by_uid = early.by_uid()
    late_by_uid = late.by_uid()
    float_by_uid = floats.by_uid()
    rows = {
        uid: (
            plan.to_datetime(early_by_uid[uid].early_start),
            plan.to_datetime(early_by_uid[uid].early_finish),
            plan.to_datetime(early_by_uid[uid].early_start),
            plan.to_datetime(early_by_uid[uid].early_finish),
            plan.to_datetime(late_by_uid[uid].late_start),
            plan.to_datetime(late_by_uid[uid].late_finish),
            float_by_uid[uid].total_float,
            float_by_uid[uid].free_float,
            float_by_uid[uid].critical,
        )
        for uid in network.activity_by_uid()
    }
    return network, early, late, floats, rows


def _mismatch_keys(observed: dict[str, tuple], engine: dict[str, tuple], leaf_by_source: dict[str, str]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for source_uid, source_row in observed.items():
        engine_row = engine.get(source_uid)
        if engine_row is None:
            continue
        for index, field in enumerate(FIELDS):
            if source_row[index] != engine_row[index]:
                keys.add((leaf_by_source[source_uid], field))
    return keys


def _delta(source_value, engine_value) -> int:
    if isinstance(source_value, datetime):
        return int((engine_value - source_value).total_seconds())
    if isinstance(source_value, bool):
        return int(engine_value) - int(source_value)
    return int(engine_value) - int(source_value)


def _movement(before: int, after: int) -> str:
    if after == 0:
        return "closed"
    if abs(after) < abs(before):
        return "improved"
    if abs(after) > abs(before):
        return "worsened"
    return "unchanged"


def _free_slack_equivalence(schedule, plan, splice_rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    """Verify the BOILER Free-Slack shape from immutable source observations.

    This guard deliberately does not read the counterfactual forward pass.  The
    splice is the thing under test, so allowing its recalculated successor dates
    to prove equivalence would be circular.  Every coordinate below comes from
    the hash-verified BOILER source imported before the diagnostic transform.
    """

    _, uid_by_leaf, _ = _leaf_maps(schedule)
    activities = {row.uid: row for row in schedule.activities}
    planned = plan.network.activity_by_uid()
    grouped: dict[tuple[str, str], list[str]] = {}
    for row in splice_rows:
        key = (row["active_predecessor_leaf_id"], row["inactive_leaf_id"])
        grouped.setdefault(key, []).append(row["active_successor_leaf_id"])

    def source_seconds(leaf_id: str, field: str) -> int:
        value = getattr(activities[uid_by_leaf[leaf_id]].source_observations, field)
        if value is None:
            raise CounterfactualError(
                f"source observation missing for {leaf_id}.{field}"
            )
        return plan.to_seconds(value)

    checks: list[dict[str, object]] = []
    for (pred_leaf, inactive_leaf), successor_leaves in sorted(grouped.items()):
        pred_uid = uid_by_leaf[pred_leaf]
        same_inactive = [
            row for row in splice_rows
            if row["inactive_leaf_id"] == inactive_leaf
        ]
        predecessor_set = {row["active_predecessor_leaf_id"] for row in same_inactive}
        if predecessor_set != {pred_leaf}:
            raise CounterfactualError(
                "multi-predecessor inactive boundary is outside this diagnostic"
            )

        pred_finish = source_seconds(pred_leaf, "early_finish")
        inactive_start = source_seconds(inactive_leaf, "early_start")
        float_calendar = planned[pred_uid].float_calendar
        inactive_gap = signed_working(float_calendar, pred_finish, inactive_start)

        direct_gaps = {
            successor_leaf: signed_working(
                float_calendar,
                pred_finish,
                source_seconds(successor_leaf, "early_start"),
            )
            for successor_leaf in sorted(successor_leaves)
        }
        source_free_slack = activities[pred_uid].source_observations.free_float_seconds
        if source_free_slack is None:
            raise CounterfactualError(
                f"source observation missing for {pred_leaf}.free_float"
            )
        all_direct_match = all(gap == inactive_gap for gap in direct_gaps.values())
        free_slack_matches = source_free_slack == inactive_gap
        equivalent = all_direct_match and free_slack_matches
        checks.append(
            {
                "active_predecessor_leaf_id": pred_leaf,
                "inactive_leaf_id": inactive_leaf,
                "active_successor_count": len(successor_leaves),
                "source_predecessor_free_slack_seconds": source_free_slack,
                "source_inactive_edge_gap_seconds": inactive_gap,
                "source_direct_successor_gap_seconds_by_leaf": direct_gaps,
                "source_free_slack_matches_inactive_edge_gap": free_slack_matches,
                "all_source_direct_successor_gaps_match_inactive_edge_gap": all_direct_match,
                "equivalent_for_this_boiler_boundary": equivalent,
            }
        )
    if not all(row["equivalent_for_this_boiler_boundary"] for row in checks):
        raise CounterfactualError(
            "direct diagnostic splice would not preserve the source-observed Free-Slack shape"
        )
    return {
        "basis": "hash-verified BOILER source observations before diagnostic transform",
        "all_equivalent": True,
        "boundaries": checks,
    }


def build_record(baseline_path: Path) -> dict[str, object]:
    if production_source_digest() != PRODUCTION_SOURCE_DIGEST:
        raise CounterfactualError("production source basis changed from fresh main")

    inventory = read_inventory()
    fixture = baseline_diag.read_verified_fixture(
        baseline_path, (BASELINE_BYTES, BASELINE_SHA256), "baseline"
    )
    schedule = baseline_diag._load(fixture.payload)
    production = baseline_diag._calculate(schedule)
    observed = baseline_diag._observed(baseline_diag._activities(schedule))
    production_engine = baseline_diag._engine(schedule, production.result)

    leaf_by_uid, _, source_uid_by_leaf = _leaf_maps(schedule)
    leaf_by_source = {source_uid: leaf for leaf, source_uid in source_uid_by_leaf.items()}
    fixed_rows = inventory["mismatches"]
    fixed_keys = {(row["leaf_id"], row["field"]) for row in fixed_rows}
    production_keys = _mismatch_keys(observed, production_engine, leaf_by_source)
    if production_keys != fixed_keys:
        raise CounterfactualError(
            "fresh-main production result no longer reproduces the exact 422-slot inventory"
        )

    splices, splice_rows = diagnostic_splices(schedule, production.plan.network)
    free_slack = _free_slack_equivalence(schedule, production.plan, splice_rows)
    network, early, late, floats, result_rows = _run_diagnostic(production.plan, splices)
    counter_engine = baseline_diag._engine(schedule, result_rows)
    counter_keys = _mismatch_keys(observed, counter_engine, leaf_by_source)
    new_keys = counter_keys - production_keys
    if new_keys:
        raise CounterfactualError(
            "diagnostic introduced mismatches outside the fixed 422-slot inventory"
        )

    fixed_by_key = {(row["leaf_id"], row["field"]): row for row in fixed_rows}
    group_before = Counter(row["diagnostic_group"] for row in fixed_rows)
    group_after = Counter(
        fixed_by_key[key]["diagnostic_group"] for key in counter_keys
    )
    field_before = Counter(row["field"] for row in fixed_rows)
    field_after = Counter(field for _, field in counter_keys)

    status_by_group: dict[str, Counter] = {}
    remaining_rc02: list[dict[str, object]] = []
    for key in sorted(fixed_keys):
        row = fixed_by_key[key]
        leaf_id, field = key
        source_uid = source_uid_by_leaf[leaf_id]
        index = FIELDS.index(field)
        before_delta = _delta(observed[source_uid][index], production_engine[source_uid][index])
        after_delta = _delta(observed[source_uid][index], counter_engine[source_uid][index])
        expected_before = row["delta"].get("sto_minus_source")
        if expected_before is not None and before_delta != expected_before:
            raise CounterfactualError(f"baseline delta changed for {leaf_id}/{field}")
        status = _movement(before_delta, after_delta)
        status_by_group.setdefault(row["diagnostic_group"], Counter())[status] += 1
        if row["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY and after_delta != 0:
            remaining_rc02.append(
                {
                    "leaf_id": leaf_id,
                    "field": field,
                    "dependency_role": row["dependency_role"],
                    "before_sto_minus_source_seconds": before_delta,
                    "after_sto_minus_source_seconds": after_delta,
                    "movement": status,
                }
            )

    rc02 = next(
        row for row in inventory["root_cause_groups"]
        if row["group_id"] == baseline_diag.INACTIVE_BOUNDARY
    )
    root_outcomes: list[dict[str, object]] = []
    for leaf_id in rc02["root_leaf_ids"]:
        first = sorted(
            row["field"] for row in fixed_rows
            if row["leaf_id"] == leaf_id
            and row["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY
            and row["dependency_role"] == "FIRST_DIVERGENCE"
        )
        remaining = sorted(field for field in first if (leaf_id, field) in counter_keys)
        root_outcomes.append(
            {
                "leaf_id": leaf_id,
                "first_divergence_fields_before": first,
                "remaining_first_divergence_fields": remaining,
                "status": "CLOSED" if not remaining else "PARTIAL",
            }
        )

    remaining_inventory_rows = [
        fixed_by_key[(row["leaf_id"], row["field"])]
        for row in remaining_rc02
    ]
    remaining_path_roots = sorted(
        {
            path[0]
            for row in remaining_inventory_rows
            for path in row.get("dependency_paths", ())
            if path
        }
    )
    fanout_residue = {
        "remaining_rc02_path_roots": remaining_path_roots,
        "remaining_rc02_leaf_count": len({row["leaf_id"] for row in remaining_rc02}),
        "remaining_rc02_by_field": dict(
            sorted(Counter(row["field"] for row in remaining_rc02).items())
        ),
        "fanout_boundary": {
            "active_predecessor_leaf_id": "L0055",
            "inactive_leaf_id": "L0052",
            "active_successor_leaf_ids": ["L0056", "L0060"],
            "active_successor_count": 2,
        },
        "single_successor_boundary": {
            "active_predecessor_leaf_id": "L0400",
            "inactive_leaf_id": "L0388",
            "active_successor_leaf_ids": ["L0389"],
            "active_successor_count": 1,
        },
        "interpretation": (
            "All remaining RC02 dependency paths root at the active predecessor "
            "of the two-active-successor inactive fan-out. This localizes the "
            "unmeasured dimension but does not establish its backward rule."
        ),
    }
    if remaining_path_roots != ["L0055"]:
        raise CounterfactualError("RC02 residue is no longer localized to the expected fan-out root")
    rc02_status = status_by_group[baseline_diag.INACTIVE_BOUNDARY]
    other_worsened = sum(
        counts.get("worsened", 0)
        for group, counts in status_by_group.items()
        if group != baseline_diag.INACTIVE_BOUNDARY
    )
    all_roots_closed = all(row["status"] == "CLOSED" for row in root_outcomes)
    rc02_has_worsening = rc02_status.get("worsened", 0) > 0
    diagnostic_pass = all_roots_closed and not rc02_has_worsening and other_worsened == 0

    return {
        "schema": SCHEMA,
        "evidence_date": EVIDENCE_DATE,
        "basis": {
            "fresh_main": MAIN_BASIS,
            "production_source_digest": PRODUCTION_SOURCE_DIGEST,
            "production_source_digest_verified": True,
            "baseline": dict(fixture.identity),
            "fixed_inventory": {
                "bytes": INVENTORY_BYTES,
                "sha256": INVENTORY_SHA256,
                "schema": inventory["schema"],
            },
            "native_semantic_evidence": "docs/evidence/p1-g2-rc02-inactive-native-matrix-2026-09-24.md",
        },
        "scope": {
            "kind": "diagnostic-only in-memory counterfactual",
            "production_scheduler_changed": False,
            "imported_schedule_changed": False,
            "tested_relationship_shape": "one-hop active -> inactive -> active zero-lag FS",
            "fanout_is_extrapolation_not_native_proof": True,
        },
        "transform": {
            "synthetic_relationship_count": len(splices),
            "splices": list(splice_rows),
            "production_network_fingerprint": production.plan.network.fingerprint(),
            "diagnostic_network_fingerprint": network.fingerprint(),
            "free_slack_shape_check": free_slack,
        },
        "inventory": {
            "before": {
                "slots": len(production_keys),
                "leaves": len({leaf for leaf, _ in production_keys}),
                "by_field": dict(sorted(field_before.items())),
                "by_group": dict(sorted(group_before.items())),
            },
            "after": {
                "slots": len(counter_keys),
                "leaves": len({leaf for leaf, _ in counter_keys}),
                "by_field": dict(sorted(field_after.items())),
                "by_group": dict(sorted(group_after.items())),
            },
            "closed_slots": len(production_keys - counter_keys),
            "new_slots": len(new_keys),
        },
        "movement_by_original_group": {
            group: dict(sorted(counts.items()))
            for group, counts in sorted(status_by_group.items())
        },
        "rc02": {
            "slots_before": group_before[baseline_diag.INACTIVE_BOUNDARY],
            "slots_after": group_after[baseline_diag.INACTIVE_BOUNDARY],
            "closed_slots": group_before[baseline_diag.INACTIVE_BOUNDARY]
            - group_after[baseline_diag.INACTIVE_BOUNDARY],
            "leaves_after": len({leaf for leaf, field in counter_keys if fixed_by_key[(leaf, field)]["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY}),
            "root_outcomes": sorted(root_outcomes, key=lambda row: row["leaf_id"]),
            "remaining_slots": remaining_rc02,
            "fanout_residue": fanout_residue,
        },
        "acceptance": {
            "fixed_422_inventory_reproduced": True,
            "no_new_mismatch_slots": not new_keys,
            "no_other_family_worsened": other_worsened == 0,
            "all_rc02_first_divergence_roots_closed": all_roots_closed,
            "all_rc02_paths_non_worsening": not rc02_has_worsening,
            "counterfactual_success": diagnostic_pass,
        },
        "decision": {
            "classification": (
                "RC02_COUNTERFACTUAL_SUPPORTED"
                if diagnostic_pass
                else "RC02_COUNTERFACTUAL_PARTIAL_SUPPORT_FANOUT_UNRESOLVED"
            ),
            "production_correction_authorized": diagnostic_pass,
            "p1_g2_closed": False,
            "p1_gate": "4/5 IN PROGRESS",
            "p2_started": False,
            "next_step": (
                "bounded native inactive-fanout experiment: one active predecessor -> one inactive middle -> two active successors with deliberately distinct late boundaries; measure backward placement and Free Slack before any production correction"
                if not diagnostic_pass
                else "separate bounded production RC02 semantic correction PR"
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


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, path)
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
    record = build_record(args.baseline)
    payload = serialize(record)
    if args.check:
        _separate(args.baseline, args.check)
        if args.check.read_bytes() != payload.encode("utf-8"):
            raise SystemExit("committed counterfactual evidence differs from exact output")
        print("committed counterfactual evidence matches exact output")
    elif args.output:
        _write_atomic(args.output, payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
