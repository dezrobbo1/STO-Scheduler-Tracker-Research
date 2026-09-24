#!/usr/bin/env python3
"""Run the bounded RC02 latest-successor BOILER diagnostic counterfactual.

This evidence tool does not modify production scheduling semantics.  It composes
three already-measured facts only for the exact BOILER P1-G2 fixture:

* inactive zero-lag FS duration is removed from forward date placement;
* predecessor Free Slack retains the inactive-edge reporting gap;
* in a one-predecessor / one-inactive / two-successor fan-out, Microsoft Project
  build 16.0.20326.20140 placed the inactive predecessor's Late Finish on the
  *latest* active-successor Late Start.

The production Network cannot represent a relationship that binds every
successor forward but only the latest-successor boundary backward.  This script
therefore keeps the full synthetic splice set for the production forward pass,
then runs a diagnostic backward pass over that same network while suppressing
only the earlier synthetic fan-out edge from the backward bound scan.  The
normal production backward helpers are reused; a regression proves that the
wrapper is byte-for-byte coordinate-equivalent to production backward_pass when
no diagnostic edge is suppressed.
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
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for import_root in (str(ROOT), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from scripts.evidence import p1_g2_baseline_diagnostics as baseline_diag
from scripts.evidence import p1_g2_rc02_boiler_counterfactual as prior_cf
from sto.core.engine import backward_pass, float_analysis, forward_pass
from sto.core.engine import backward as backward_mod
from sto.core.engine.backward import ActivityLateTimes, BackwardPass, DeferredLateConstraint
from sto.core.engine.progress import ProgressState, relationship_binds, state_of
from sto.core.hashing import canonical_sha256
from sto.core.model.enums import ConstraintType

SCHEMA = "sto-p1-g2-rc02-latest-successor-boiler-counterfactual-v1"
EVIDENCE_DATE = "2026-09-25"
MAIN_BASIS = "d6ce148e6d3ff489d5173a99ebd2f0c4176de636"
PRODUCTION_SOURCE_DIGEST = "22e8bf15ed5181067b8294a0f6cb6b1b46d1612c216e8d11985284f5759ecac5"
BASELINE_BYTES, BASELINE_SHA256 = baseline_diag.BASELINE_IDENTITY
FIELDS = tuple(baseline_diag.RESULT_FIELDS)

NATIVE_RESULT_PATH = ROOT / "docs/evidence/p1-g2-rc02-inactive-fanout-native-result-2026-09-25.json"
NATIVE_RESULT_BYTES = 34_512
NATIVE_RESULT_SHA256 = "509c0bed75c6032024d7088e5da330f17b07a27322c48b45332dfce8577daf44"
NATIVE_BUILD = "16.0.20326.20140"

PRIOR_RESULT_PATH = ROOT / "docs/evidence/p1-g2-rc02-boiler-counterfactual-2026-09-24.json"
PRIOR_RESULT_BYTES = 12_191
PRIOR_RESULT_SHA256 = "3ba80ee3db6bd6a6a3be3349ed8621e23b5269fde86c3a789bb18d8d48292769"
PRIOR_TOOL_PATH = ROOT / "scripts/evidence/p1_g2_rc02_boiler_counterfactual.py"
PRIOR_TOOL_BYTES = 26_310
PRIOR_TOOL_SHA256 = "bda6daa6cf1b741b661814738adf1c3f3a1c1139b024c4096ccf2571cc4e4696"

EXPECTED_SELECTED = frozenset(
    {
        ("L0055", "L0052", "L0060"),
        ("L0400", "L0388", "L0389"),
    }
)
EXPECTED_DROPPED_BACKWARD = frozenset({("L0055", "L0052", "L0056")})


class LatestSuccessorCounterfactualError(RuntimeError):
    """The bounded diagnostic contract no longer holds."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()



def evidence_tool_identity() -> dict[str, object]:
    payload = Path(__file__).read_bytes()
    return {
        "path": "scripts/evidence/p1_g2_rc02_latest_successor_boiler_counterfactual.py",
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }


def verify_dependency_identity() -> dict[str, object]:
    payload = PRIOR_TOOL_PATH.read_bytes()
    if len(payload) != PRIOR_TOOL_BYTES or _sha256(payload) != PRIOR_TOOL_SHA256:
        raise LatestSuccessorCounterfactualError("prior counterfactual tool identity changed")
    return {
        "path": "scripts/evidence/p1_g2_rc02_boiler_counterfactual.py",
        "bytes": PRIOR_TOOL_BYTES,
        "sha256": PRIOR_TOOL_SHA256,
    }


def _read_pinned_json(path: Path, size: int, sha256: str, label: str) -> dict[str, object]:
    payload = path.read_bytes()
    if len(payload) != size or _sha256(payload) != sha256:
        raise LatestSuccessorCounterfactualError(f"{label} identity changed")
    return json.loads(payload)


def read_native_result() -> dict[str, object]:
    record = _read_pinned_json(
        NATIVE_RESULT_PATH,
        NATIVE_RESULT_BYTES,
        NATIVE_RESULT_SHA256,
        "native fan-out result",
    )
    if record.get("schema") != "sto-p1-g2-rc02-fanout-native-v1":
        raise LatestSuccessorCounterfactualError("unexpected native fan-out schema")
    if record.get("project", {}).get("build_number") != NATIVE_BUILD:
        raise LatestSuccessorCounterfactualError("native fan-out Project build changed")
    classification = record.get("classification", {})
    if classification.get("controls", {}).get("valid") is not True:
        raise LatestSuccessorCounterfactualError("native fan-out controls are not valid")
    components = classification.get("components", {})
    expected_components = {
        "forward_semantic": "ZERO_DURATION_FANOUT_FORWARD_PASSTHROUGH_SUPPORTED",
        "backward_semantic": "LATEST_ACTIVE_SUCCESSOR_LATE_BOUNDARY_SUPPORTED",
        "free_slack_observation": "SENTINEL_CHANGED_MATCHES_INACTIVE_EDGE_GAP",
    }
    if components != expected_components:
        raise LatestSuccessorCounterfactualError("native fan-out components changed")
    if classification.get("decision", {}).get("production_scheduler_change_authorized") is not False:
        raise LatestSuccessorCounterfactualError("native experiment unexpectedly authorized production")
    return record


def read_prior_counterfactual() -> dict[str, object]:
    record = _read_pinned_json(
        PRIOR_RESULT_PATH,
        PRIOR_RESULT_BYTES,
        PRIOR_RESULT_SHA256,
        "prior BOILER counterfactual",
    )
    if record.get("schema") != "sto-p1-g2-rc02-boiler-counterfactual-v1":
        raise LatestSuccessorCounterfactualError("unexpected prior counterfactual schema")
    if record.get("inventory", {}).get("after", {}).get("slots") != 166:
        raise LatestSuccessorCounterfactualError("prior counterfactual slot count changed")
    if record.get("rc02", {}).get("slots_after") != 19:
        raise LatestSuccessorCounterfactualError("prior counterfactual RC02 residue changed")
    return record


def _directional_backward_pass(
    network,
    forward,
    *,
    dropped_relationship_uids: frozenset[UUID],
) -> BackwardPass:
    """Production backward semantics with one bounded relationship filter.

    Except for filtering ``dropped_relationship_uids`` out of each activity's
    outgoing bound scan, this mirrors ``sto.core.engine.backward.backward_pass``
    on current main and calls the production module's private placement/bound/
    driver/fingerprint helpers.  It runs only in evidence tooling.
    """

    network.validate()
    network_fingerprint = network.fingerprint()
    if forward.network_fingerprint != network_fingerprint:
        raise backward_mod.BackwardPassError(
            "SCHEDULE_PASS_MISMATCH",
            None,
            "the forward pass was computed over a different network",
        )

    progress_policy = forward.progress_policy
    snap_milestones = forward.snap_milestones
    by_uid = network.activity_by_uid()
    raw_outgoing = network.successors()
    outgoing = {
        uid: tuple(rel for rel in relationships if rel.uid not in dropped_relationship_uids)
        for uid, relationships in raw_outgoing.items()
    }
    late_finish = forward.project_finish
    if late_finish > network.horizon:
        raise backward_mod.BackwardPassError(
            "SCHEDULE_HORIZON_EXCEEDED",
            None,
            f"project late finish {late_finish} lies beyond the compiled horizon {network.horizon}",
        )

    calendars = {activity.uid: activity.calendar for activity in network.activities}
    early = forward.by_uid()
    states = {activity.uid: state_of(activity) for activity in network.activities}
    overridden = tuple(
        relationship.uid
        for relationship in network.relationships
        if not relationship_binds(
            progress_policy,
            states[relationship.successor_uid],
            network.status_time,
        )
    )
    released = frozenset(overridden)

    placed: dict[UUID, ActivityLateTimes] = {}
    deferred: list[DeferredLateConstraint] = []

    for uid in reversed(forward.order):
        activity = by_uid[uid]
        state = states[uid]
        progressed = state is not ProgressState.NOT_STARTED
        if progressed and activity.constraint_type is not ConstraintType.ASAP:
            deferred.append(DeferredLateConstraint(uid, activity.constraint_type))
        if state is ProgressState.COMPLETE:
            if activity.actual_start is None or activity.actual_finish is None:
                raise backward_mod.BackwardPassError(
                    "SCHEDULE_ACTUAL_FINISH_WITHOUT_START", activity.uid
                )
            placed[uid] = ActivityLateTimes(
                uid,
                activity.actual_start,
                activity.actual_finish,
                None,
                backward_mod.FROM_ACTUALS,
            )
            continue

        start_bound, finish_bound, start_driver, finish_driver = backward_mod._bounds(
            activity,
            outgoing[uid],
            placed,
            early,
            late_finish,
            calendars,
            released,
            network.horizon,
        )

        constraint = activity.constraint_type
        coordinate = activity.constraint_coordinate
        pinned: str | None = None
        constrained = False
        if not progressed:
            if constraint is ConstraintType.ALAP:
                deferred.append(DeferredLateConstraint(uid, constraint))
            elif constraint is ConstraintType.SNLT and coordinate is not None:
                if coordinate < start_bound:
                    start_bound, start_driver, constrained = coordinate, None, True
            elif constraint is ConstraintType.FNLT and coordinate is not None:
                if coordinate < finish_bound:
                    finish_bound, finish_driver, constrained = coordinate, None, True
            elif constraint is ConstraintType.MSO and coordinate is not None:
                pinned = "start"
            elif constraint is ConstraintType.MFO and coordinate is not None:
                pinned = "finish"

        start, finish = backward_mod._place(
            activity,
            activity.remaining,
            start_bound,
            finish_bound,
            snap_milestones,
            pinned,
            coordinate,
        )

        if pinned is not None or constrained:
            source, driver = backward_mod.FROM_CONSTRAINT, None
        else:
            driver = backward_mod._driver(
                activity,
                activity.remaining,
                start_bound,
                finish_bound,
                start_driver,
                finish_driver,
                late_finish,
            )
            source = (
                backward_mod.FROM_RELATIONSHIP
                if driver is not None
                else backward_mod.FROM_PROJECT_FINISH
            )

        if state is ProgressState.IN_PROGRESS:
            if activity.actual_start is None:
                raise backward_mod.BackwardPassError(
                    "SCHEDULE_PROGRESS_STATE_INCOMPLETE", activity.uid
                )
            placed[uid] = ActivityLateTimes(
                uid,
                activity.actual_start,
                finish,
                driver,
                source,
                remaining_start=start,
            )
        else:
            placed[uid] = ActivityLateTimes(uid, start, finish, driver, source)

    times = tuple(placed[uid] for uid in forward.order)
    production_shape_fingerprint = backward_mod._fingerprint(
        times,
        late_finish,
        overridden,
        progress_policy,
        snap_milestones,
    )
    diagnostic_fingerprint = canonical_sha256(
        {
            "profile": "sto-evidence-p1-g2-rc02-latest-successor-backward-v1",
            "production_shape_fingerprint": production_shape_fingerprint,
            "dropped_relationship_uids": sorted(str(uid) for uid in dropped_relationship_uids),
            "native_evidence_sha256": NATIVE_RESULT_SHA256,
        }
    )
    return BackwardPass(
        times=times,
        order=tuple(reversed(forward.order)),
        project_late_finish=late_finish,
        deferred_constraints=tuple(deferred),
        fingerprint=diagnostic_fingerprint,
        overridden_relationships=overridden,
        network_fingerprint=network_fingerprint,
        progress_policy=progress_policy,
        snap_milestones=snap_milestones,
    )


def _backward_equivalent(left: BackwardPass, right: BackwardPass) -> bool:
    return (
        left.times == right.times
        and left.order == right.order
        and left.project_late_finish == right.project_late_finish
        and left.deferred_constraints == right.deferred_constraints
        and left.overridden_relationships == right.overridden_relationships
        and left.network_fingerprint == right.network_fingerprint
        and left.progress_policy is right.progress_policy
        and left.snap_milestones == right.snap_milestones
    )


def _select_latest_successor(
    schedule,
    plan,
    splices,
    splice_rows,
    symmetric_backward: BackwardPass,
) -> tuple[tuple, frozenset[UUID], tuple[dict[str, object], ...]]:
    leaf_by_uid, uid_by_leaf, _ = prior_cf._leaf_maps(schedule)
    late_by_uid = symmetric_backward.by_uid()
    activities = {row.uid: row for row in schedule.activities}

    relationship_by_tuple = {
        (
            leaf_by_uid[row.predecessor_uid],
            next(
                evidence["inactive_leaf_id"]
                for evidence in splice_rows
                if evidence["active_predecessor_leaf_id"] == leaf_by_uid[row.predecessor_uid]
                and evidence["active_successor_leaf_id"] == leaf_by_uid[row.successor_uid]
            ),
            leaf_by_uid[row.successor_uid],
        ): row
        for row in splices
    }

    grouped: dict[tuple[str, str], list[str]] = {}
    for row in splice_rows:
        grouped.setdefault(
            (row["active_predecessor_leaf_id"], row["inactive_leaf_id"]), []
        ).append(row["active_successor_leaf_id"])

    selected_tuples: set[tuple[str, str, str]] = set()
    evidence_rows: list[dict[str, object]] = []
    for (pred_leaf, inactive_leaf), successors in sorted(grouped.items()):
        candidates: list[dict[str, object]] = []
        for successor_leaf in sorted(successors):
            successor_uid = uid_by_leaf[successor_leaf]
            calculated_late = plan.to_datetime(late_by_uid[successor_uid].late_start)
            source_late = activities[successor_uid].source_observations.late_start
            if source_late is None:
                raise LatestSuccessorCounterfactualError(
                    f"source LateStart missing for {successor_leaf}"
                )
            if calculated_late != source_late:
                raise LatestSuccessorCounterfactualError(
                    f"candidate successor LateStart is not source-aligned for {successor_leaf}"
                )
            candidates.append(
                {
                    "successor_leaf_id": successor_leaf,
                    "calculated_late_start": calculated_late.isoformat(),
                    "source_late_start": source_late.isoformat(),
                    "coordinate": late_by_uid[successor_uid].late_start,
                }
            )
        latest_coordinate = max(int(row["coordinate"]) for row in candidates)
        winners = [row for row in candidates if row["coordinate"] == latest_coordinate]
        if len(winners) != 1:
            raise LatestSuccessorCounterfactualError(
                f"latest-successor boundary is tied for {pred_leaf}/{inactive_leaf}"
            )
        winner = winners[0]["successor_leaf_id"]
        selected_tuples.add((pred_leaf, inactive_leaf, str(winner)))
        evidence_rows.append(
            {
                "active_predecessor_leaf_id": pred_leaf,
                "inactive_leaf_id": inactive_leaf,
                "candidates": [
                    {
                        "successor_leaf_id": row["successor_leaf_id"],
                        "calculated_late_start": row["calculated_late_start"],
                        "source_late_start": row["source_late_start"],
                    }
                    for row in candidates
                ],
                "selected_latest_successor_leaf_id": winner,
            }
        )

    if frozenset(selected_tuples) != EXPECTED_SELECTED:
        raise LatestSuccessorCounterfactualError(
            f"latest-successor selection changed: {sorted(selected_tuples)}"
        )
    selected_relationships = tuple(
        relationship_by_tuple[row] for row in sorted(selected_tuples)
    )
    selected_uids = {row.uid for row in selected_relationships}
    dropped = frozenset(row.uid for row in splices if row.uid not in selected_uids)
    dropped_tuples = frozenset(
        key for key, relationship in relationship_by_tuple.items() if relationship.uid in dropped
    )
    if dropped_tuples != EXPECTED_DROPPED_BACKWARD:
        raise LatestSuccessorCounterfactualError(
            f"backward-only dropped splice set changed: {sorted(dropped_tuples)}"
        )
    return selected_relationships, dropped, tuple(evidence_rows)


def _result_rows(plan, network, forward, backward, floats) -> dict[UUID, tuple]:
    early_by_uid = forward.by_uid()
    late_by_uid = backward.by_uid()
    float_by_uid = floats.by_uid()
    return {
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


def _inventory_summary(keys: set[tuple[str, str]], fixed_by_key) -> dict[str, object]:
    return {
        "slots": len(keys),
        "leaves": len({leaf for leaf, _ in keys}),
        "by_field": dict(sorted(Counter(field for _, field in keys).items())),
        "by_group": dict(
            sorted(Counter(fixed_by_key[key]["diagnostic_group"] for key in keys).items())
        ),
    }


def build_record(baseline_path: Path) -> dict[str, object]:
    startup_tool_identity = evidence_tool_identity()
    dependency_identity = verify_dependency_identity()
    if prior_cf.production_source_digest() != PRODUCTION_SOURCE_DIGEST:
        raise LatestSuccessorCounterfactualError(
            "production source basis changed from the predeclared main"
        )
    native = read_native_result()
    prior = read_prior_counterfactual()
    inventory = prior_cf.read_inventory()

    fixture = baseline_diag.read_verified_fixture(
        baseline_path,
        (BASELINE_BYTES, BASELINE_SHA256),
        "baseline",
    )
    schedule = baseline_diag._load(fixture.payload)
    production = baseline_diag._calculate(schedule)
    observed = baseline_diag._observed(baseline_diag._activities(schedule))
    production_engine = baseline_diag._engine(schedule, production.result)

    _, _, source_uid_by_leaf = prior_cf._leaf_maps(schedule)
    leaf_by_source = {source_uid: leaf for leaf, source_uid in source_uid_by_leaf.items()}
    fixed_rows = inventory["mismatches"]
    fixed_by_key = {(row["leaf_id"], row["field"]): row for row in fixed_rows}
    fixed_keys = set(fixed_by_key)
    production_keys = prior_cf._mismatch_keys(observed, production_engine, leaf_by_source)
    if production_keys != fixed_keys:
        raise LatestSuccessorCounterfactualError(
            "fresh-main production no longer reproduces the exact 422-slot inventory"
        )

    splices, splice_rows = prior_cf.diagnostic_splices(schedule, production.plan.network)
    free_slack = prior_cf._free_slack_equivalence(schedule, production.plan, splice_rows)
    full_network = replace(
        production.plan.network,
        relationships=production.plan.network.relationships + splices,
    )
    full_forward = forward_pass(
        full_network,
        snap_milestones=production.plan.snap_milestones,
        progress_policy=production.plan.progress_policy,
    )
    symmetric_backward = backward_pass(
        full_network,
        full_forward,
        snap_milestones=production.plan.snap_milestones,
        progress_policy=production.plan.progress_policy,
    )
    symmetric_floats = float_analysis(
        full_network,
        full_forward,
        symmetric_backward,
        threshold=production.plan.critical_float_threshold,
    )
    symmetric_rows = _result_rows(
        production.plan,
        full_network,
        full_forward,
        symmetric_backward,
        symmetric_floats,
    )
    symmetric_engine = baseline_diag._engine(schedule, symmetric_rows)
    symmetric_keys = prior_cf._mismatch_keys(observed, symmetric_engine, leaf_by_source)
    if len(symmetric_keys) != prior["inventory"]["after"]["slots"]:
        raise LatestSuccessorCounterfactualError(
            "symmetric direct-splice stage no longer reproduces the prior counterfactual"
        )
    symmetric_rc02 = {
        key for key in symmetric_keys
        if fixed_by_key[key]["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY
    }
    if len(symmetric_rc02) != prior["rc02"]["slots_after"]:
        raise LatestSuccessorCounterfactualError(
            "symmetric RC02 residue no longer reproduces the prior counterfactual"
        )

    selected_relationships, dropped_backward, selection = _select_latest_successor(
        schedule,
        production.plan,
        splices,
        splice_rows,
        symmetric_backward,
    )

    # Fidelity guard: with no diagnostic suppression the wrapper must reproduce
    # production backward coordinates and metadata exactly (fingerprint excepted).
    wrapper_unfiltered = _directional_backward_pass(
        full_network,
        full_forward,
        dropped_relationship_uids=frozenset(),
    )
    if not _backward_equivalent(wrapper_unfiltered, symmetric_backward):
        raise LatestSuccessorCounterfactualError(
            "diagnostic backward wrapper diverges from production when unfiltered"
        )

    directional_backward = _directional_backward_pass(
        full_network,
        full_forward,
        dropped_relationship_uids=dropped_backward,
    )
    directional_floats = float_analysis(
        full_network,
        full_forward,
        directional_backward,
        threshold=production.plan.critical_float_threshold,
    )
    directional_rows = _result_rows(
        production.plan,
        full_network,
        full_forward,
        directional_backward,
        directional_floats,
    )
    directional_engine = baseline_diag._engine(schedule, directional_rows)
    directional_keys = prior_cf._mismatch_keys(observed, directional_engine, leaf_by_source)
    new_keys = directional_keys - production_keys
    if new_keys:
        raise LatestSuccessorCounterfactualError(
            "latest-successor diagnostic introduced mismatches outside the fixed 422-slot inventory"
        )

    status_by_group: dict[str, Counter] = {}
    for key in sorted(fixed_keys):
        row = fixed_by_key[key]
        leaf_id, field = key
        source_uid = source_uid_by_leaf[leaf_id]
        index = FIELDS.index(field)
        before_delta = prior_cf._delta(
            observed[source_uid][index], production_engine[source_uid][index]
        )
        after_delta = prior_cf._delta(
            observed[source_uid][index], directional_engine[source_uid][index]
        )
        expected_before = row["delta"].get("sto_minus_source")
        if expected_before is not None and before_delta != expected_before:
            raise LatestSuccessorCounterfactualError(
                f"baseline delta changed for {leaf_id}/{field}"
            )
        status = prior_cf._movement(before_delta, after_delta)
        status_by_group.setdefault(row["diagnostic_group"], Counter())[status] += 1

    rc02_keys = {
        key for key in directional_keys
        if fixed_by_key[key]["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY
    }
    rc02 = next(
        row for row in inventory["root_cause_groups"]
        if row["group_id"] == baseline_diag.INACTIVE_BOUNDARY
    )
    root_outcomes: list[dict[str, object]] = []
    for leaf_id in rc02["root_leaf_ids"]:
        first = sorted(
            row["field"]
            for row in fixed_rows
            if row["leaf_id"] == leaf_id
            and row["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY
            and row["dependency_role"] == "FIRST_DIVERGENCE"
        )
        remaining = sorted(field for field in first if (leaf_id, field) in rc02_keys)
        root_outcomes.append(
            {
                "leaf_id": leaf_id,
                "first_divergence_fields_before": first,
                "remaining_first_divergence_fields": remaining,
                "status": "CLOSED" if not remaining else "PARTIAL",
            }
        )

    other_worsened = sum(
        counts.get("worsened", 0)
        for group, counts in status_by_group.items()
        if group != baseline_diag.INACTIVE_BOUNDARY
    )
    all_roots_closed = all(row["status"] == "CLOSED" for row in root_outcomes)
    all_rc02_closed = not rc02_keys
    rc02_has_worsening = status_by_group[baseline_diag.INACTIVE_BOUNDARY].get("worsened", 0) > 0
    exact_prior_residue_closed = symmetric_keys - directional_keys == symmetric_rc02
    diagnostic_pass = (
        all_roots_closed
        and all_rc02_closed
        and not rc02_has_worsening
        and other_worsened == 0
        and not new_keys
        and exact_prior_residue_closed
    )

    selected_tuples = [
        {
            "predecessor_leaf_id": row["active_predecessor_leaf_id"],
            "inactive_leaf_id": row["inactive_leaf_id"],
            "successor_leaf_id": row["selected_latest_successor_leaf_id"],
        }
        for row in selection
    ]

    if evidence_tool_identity() != startup_tool_identity:
        raise LatestSuccessorCounterfactualError("evidence tool bytes changed during execution")

    return {
        "schema": SCHEMA,
        "evidence_date": EVIDENCE_DATE,
        "basis": {
            "fresh_main": MAIN_BASIS,
            "evidence_tool": startup_tool_identity,
            "prior_counterfactual_tool": dependency_identity,
            "production_source_digest": PRODUCTION_SOURCE_DIGEST,
            "production_source_digest_verified": True,
            "baseline": dict(fixture.identity),
            "fixed_inventory": {
                "bytes": prior_cf.INVENTORY_BYTES,
                "sha256": prior_cf.INVENTORY_SHA256,
                "schema": inventory["schema"],
            },
            "native_fanout_result": {
                "bytes": NATIVE_RESULT_BYTES,
                "sha256": NATIVE_RESULT_SHA256,
                "project_build": NATIVE_BUILD,
                "forward_semantic": native["classification"]["components"]["forward_semantic"],
                "backward_semantic": native["classification"]["components"]["backward_semantic"],
                "free_slack_observation": native["classification"]["components"]["free_slack_observation"],
                "original_combined_authorization_passed": native["classification"]["decision"]["boiler_counterfactual_rerun_authorized"],
            },
            "prior_symmetric_counterfactual": {
                "bytes": PRIOR_RESULT_BYTES,
                "sha256": PRIOR_RESULT_SHA256,
                "slots_after": prior["inventory"]["after"]["slots"],
                "rc02_slots_after": prior["rc02"]["slots_after"],
            },
        },
        "scope": {
            "kind": "diagnostic-only directional in-memory counterfactual",
            "production_scheduler_changed": False,
            "imported_schedule_changed": False,
            "production_network_model_changed": False,
            "forward_semantic": "all exact active->inactive->active zero-lag FS boundaries receive direct zero-lag forward splices",
            "backward_semantic": "for each such inactive boundary, only the direct splice to the unique latest calculated active-successor LateStart participates in the predecessor backward bound",
            "selection_guard": "candidate successor calculated LateStarts must already equal immutable BOILER source LateStarts before selection",
        },
        "transform": {
            "full_forward_splice_count": len(splices),
            "full_forward_splices": list(splice_rows),
            "latest_successor_selection": list(selection),
            "selected_backward_splices": selected_tuples,
            "dropped_backward_splice_count": len(dropped_backward),
            "dropped_backward_splices": [
                {
                    "predecessor_leaf_id": "L0055",
                    "inactive_leaf_id": "L0052",
                    "successor_leaf_id": "L0056",
                }
            ],
            "free_slack_shape_check": free_slack,
            "production_network_fingerprint": production.plan.network.fingerprint(),
            "full_directional_network_fingerprint": full_network.fingerprint(),
            "symmetric_backward_fingerprint": symmetric_backward.fingerprint,
            "directional_backward_fingerprint": directional_backward.fingerprint,
            "unfiltered_wrapper_matches_production_backward": True,
        },
        "inventory": {
            "production": _inventory_summary(production_keys, fixed_by_key),
            "symmetric_direct_splice": _inventory_summary(symmetric_keys, fixed_by_key),
            "latest_successor_directional": _inventory_summary(directional_keys, fixed_by_key),
            "closed_from_production": len(production_keys - directional_keys),
            "closed_from_prior_symmetric": len(symmetric_keys - directional_keys),
            "new_slots": len(new_keys),
        },
        "movement_by_original_group": {
            group: dict(sorted(counts.items()))
            for group, counts in sorted(status_by_group.items())
        },
        "rc02": {
            "slots_before": sum(
                1 for row in fixed_rows
                if row["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY
            ),
            "slots_after_symmetric": len(symmetric_rc02),
            "slots_after_latest_successor": len(rc02_keys),
            "closed_slots_from_production": sum(
                1 for key in fixed_keys
                if fixed_by_key[key]["diagnostic_group"] == baseline_diag.INACTIVE_BOUNDARY
                and key not in directional_keys
            ),
            "root_outcomes": sorted(root_outcomes, key=lambda row: row["leaf_id"]),
            "exact_prior_19_slot_residue_closed": exact_prior_residue_closed,
        },
        "acceptance": {
            "fixed_422_inventory_reproduced": production_keys == fixed_keys,
            "native_latest_successor_basis_verified": True,
            "prior_166_slot_symmetric_stage_reproduced": len(symmetric_keys) == 166,
            "prior_19_slot_rc02_residue_reproduced": len(symmetric_rc02) == 19,
            "selection_late_starts_source_aligned": True,
            "unfiltered_wrapper_matches_production_backward": True,
            "no_new_mismatch_slots": not new_keys,
            "no_other_family_worsened": other_worsened == 0,
            "all_rc02_first_divergence_roots_closed": all_roots_closed,
            "all_rc02_slots_closed": all_rc02_closed,
            "all_rc02_paths_non_worsening": not rc02_has_worsening,
            "exact_prior_19_slot_residue_closed": exact_prior_residue_closed,
            "counterfactual_success": diagnostic_pass,
        },
        "decision": {
            "classification": (
                "RC02_LATEST_SUCCESSOR_COUNTERFACTUAL_SUPPORTED"
                if diagnostic_pass
                else "RC02_LATEST_SUCCESSOR_COUNTERFACTUAL_NOT_SUPPORTED"
            ),
            "separate_bounded_production_rc02_correction_pr_authorized": diagnostic_pass,
            "production_scheduler_changed": False,
            "p1_g2_closed": False,
            "p1_gate": "4/5 IN PROGRESS",
            "p2_started": False,
            "next_step": (
                "separate bounded production RC02 semantic correction PR; implement only the measured directional inactive-boundary rule, then rerun the exact 422-slot BOILER inventory and the real-file forward/backward/conformance cohorts"
                if diagnostic_pass
                else "do not change production RC02 semantics; isolate the remaining counterfactual failure"
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


def _write_atomic(source: Path, path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        _separate(source, path)
        os.replace(temporary, path)
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
            raise SystemExit("committed latest-successor BOILER evidence differs from exact output")
        print("committed latest-successor BOILER evidence matches exact output")
    elif args.output:
        _write_atomic(args.baseline, args.output, payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
