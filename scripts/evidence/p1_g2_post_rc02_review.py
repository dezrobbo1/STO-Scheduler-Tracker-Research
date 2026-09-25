#!/usr/bin/env python3
"""Recompute the post-RC02 P1-G2 roots with current production primitives.

The raw BOILER baseline is external and immutable.  The committed output is a
sanitized append-only follow-up to the historical diagnosis; historical group
and dependency labels are never inputs to the current classification.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for import_root in (str(ROOT), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from scripts.evidence import p1_g2_baseline_diagnostics as baseline_diag
from scripts.evidence import p1_g2_rc01_assignment_native_generate as rc01_generate
from scripts.evidence import p1_g2_rc02_boiler_counterfactual as prior_cf
from scripts.evidence import p1_g2_rc02_production_verification as production
from sto.core.engine.validate import validate_result

SCHEMA = "sto-p1-g2-post-rc02-review-v2"
EVIDENCE_DATE = "2026-09-25"
REPOSITORY_BASE = "a4a401c42dcacfb3122467b017607aa6be1ee0e5"

HISTORICAL_PATH = ROOT / "docs/evidence/p1-g2-baseline-root-causes-2026-09-22.json"
HISTORICAL_BLOB_SHA = "f4eeb06bccb9681342db58ef84a06fa2c26742f8"
POST_RC02_PATH = ROOT / "docs/evidence/p1-g2-rc02-production-correction-2026-09-25.json"
POST_RC02_BLOB_SHA = "5ea13c477735bf52bd2ee2e07c62597036b09f2b"


class EvidenceError(ValueError):
    """The current calculation or evidence inputs do not satisfy the contract."""


def _git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_pinned(path: Path, expected_blob_sha: str) -> dict[str, object]:
    payload = path.read_bytes()
    actual = _git_blob_sha(payload)
    if actual != expected_blob_sha:
        raise EvidenceError(
            f"{path.relative_to(ROOT)} blob changed: expected {expected_blob_sha}, got {actual}"
        )
    return json.loads(payload)


def load_inputs() -> tuple[dict[str, object], dict[str, object]]:
    return (
        _read_pinned(HISTORICAL_PATH, HISTORICAL_BLOB_SHA),
        _read_pinned(POST_RC02_PATH, POST_RC02_BLOB_SHA),
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _counts(rows: list[dict[str, object]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows).items()))


def _leaf_count(rows: list[dict[str, object]]) -> int:
    return len({str(row["leaf_id"]) for row in rows})


def _group(historical: Mapping[str, object], group_id: str) -> dict[str, object]:
    groups = {
        str(row["group_id"]): row
        for row in historical["root_cause_groups"]  # type: ignore[index]
    }
    try:
        return groups[group_id]
    except KeyError as exc:
        raise EvidenceError(f"historical evidence is missing {group_id}") from exc


def _leaf(value: str | None, leaf_by_source: Mapping[str, str]) -> str | None:
    return None if value is None else leaf_by_source[value]


def recompute_current(baseline_path: Path) -> dict[str, object]:
    """Classify every current mismatch from a fresh production calculation."""

    basis = production.verify_current_production_basis()
    fixture = baseline_diag.read_verified_fixture(
        baseline_path,
        baseline_diag.BASELINE_IDENTITY,
        "BOILER baseline",
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
        raise EvidenceError(
            "current production result does not validate: "
            + ", ".join(row.code for row in violations[:10])
        )

    activities = baseline_diag._activities(schedule)
    observed = baseline_diag._observed(activities)
    engine = baseline_diag._engine(schedule, calculation.result)
    leaf_by_uid, uid_by_leaf, source_by_leaf = prior_cf._leaf_maps(schedule)
    leaf_by_source = {source: leaf for leaf, source in source_by_leaf.items()}
    current_keys = prior_cf._mismatch_keys(observed, engine, leaf_by_source)

    coordinate, replay_drivers, source_early, source_late = (
        baseline_diag._coordinate_provenance(schedule, calculation)
    )
    provenance = dict(coordinate)
    provenance.update(
        baseline_diag._float_provenance(
            schedule,
            calculation,
            coordinate,
            source_early,
            source_late,
        )
    )
    forward_drivers, late_drivers = baseline_diag._driver_source_uids(
        schedule, calculation
    )
    mismatch_uids = {uid_by_leaf[leaf] for leaf, _ in current_keys}
    _, component_by_uid = baseline_diag._components(
        mismatch_uids,
        schedule,
        calculation,
        leaf_by_source,
    )
    affected_sources = {source_by_leaf[leaf] for leaf, _ in current_keys}
    uid_by_source = {
        baseline_diag._source_uid(row): row.uid for row in schedule.activities
    }

    rows: list[dict[str, object]] = []
    for leaf_id, field in sorted(current_keys):
        source_uid = source_by_leaf[leaf_id]
        uid = uid_by_source[source_uid]
        basis_field = {"start": "early_start", "finish": "early_finish"}.get(
            field, field
        )
        cause = provenance.get((uid, basis_field))
        if cause is None:
            cause = baseline_diag.Provenance(
                baseline_diag.UNKNOWN,
                "ROOT",
                ((source_uid,),),
            )
        source_value = observed[source_uid][baseline_diag.RESULT_FIELDS.index(field)]
        engine_value = engine[source_uid][baseline_diag.RESULT_FIELDS.index(field)]
        forward_driver = forward_drivers[uid]
        late_driver = late_drivers[uid]
        rows.append(
            {
                "leaf_id": leaf_id,
                "field": field,
                "sto_minus_source_seconds": prior_cf._delta(source_value, engine_value),
                "diagnostic_group": cause.group_id,
                "causal_confidence": baseline_diag.GROUP_DEFINITIONS[cause.group_id][
                    "causal_confidence"
                ],
                "dependency_role": baseline_diag.DEPENDENCY_ROLES[cause.causality],
                "dependency_paths": [
                    [leaf_by_source[path_source] for path_source in path]
                    for path in cause.paths
                ],
                "component_id": component_by_uid[uid],
                "forward_driver_predecessor_leaf_id": _leaf(
                    forward_driver, leaf_by_source
                ),
                "late_driver_successor_leaf_id": _leaf(late_driver, leaf_by_source),
                "source_replay_driver_leaf_id": _leaf(
                    replay_drivers.get((uid, basis_field)), leaf_by_source
                ),
                "mismatched_engine_driver": (
                    forward_driver in affected_sources
                    if field in {"start", "finish", "early_start", "early_finish"}
                    else late_driver in affected_sources
                    if field in {"late_start", "late_finish"}
                    else None
                ),
            }
        )

    roots = {
        str(row["leaf_id"])
        for row in rows
        if row["dependency_role"] in {"FIRST_DIVERGENCE", "COMPOUND"}
    }
    root_context = {
        leaf_id: baseline_diag._activity_context(
            schedule, calculation, uid_by_leaf[leaf_id]
        )
        for leaf_id in sorted(roots)
    }
    projection_payload, projection_sha = production._projection(engine, leaf_by_source)
    del projection_payload
    return {
        "method": "CURRENT_PRODUCTION_SOURCE_COORDINATE_REPLAY",
        "method_contract": {
            "forward": "source predecessor coordinates through current forward bounds/place/driver",
            "backward": "source successor late coordinates through current backward bounds/place/driver",
            "float": "source early/late coordinates through current production float analysis",
            "start_finish": "duplicate the corresponding recomputed early-coordinate provenance",
            "critical": "derive provenance from recomputed Total Float only",
        },
        "fixture": dict(fixture.identity),
        "production_basis": {
            "commit": production.PRODUCTION_COMMIT,
            "path_tree_sha256": basis["path_tree_sha256"],
            "verified_against_worktree": basis["verified_against_worktree"],
            "projection_sha256": projection_sha,
            "remaining_keyset_sha256": production._keyset_sha(current_keys),
        },
        "mismatches": rows,
        "root_activity_context": root_context,
    }


def review_documents(
    historical: dict[str, object],
    post_rc02: dict[str, object],
    recomputation: dict[str, object],
) -> dict[str, object]:
    _require(
        historical.get("schema") == "sto-p1-g2-baseline-root-causes-v3",
        "unexpected historical root-cause schema",
    )
    _require(
        post_rc02.get("schema") == "sto-p1-g2-rc02-production-verification-v1",
        "unexpected post-RC02 schema",
    )
    decision = post_rc02["decision"]  # type: ignore[index]
    _require(
        decision["classification"] == "RC02_PRODUCTION_CORRECTION_VERIFIED"
        and decision["rc02_closed_in_production"] is True,
        "RC02 is not verified closed in the supplied production evidence",
    )
    _require(
        recomputation.get("method") == "CURRENT_PRODUCTION_SOURCE_COORDINATE_REPLAY",
        "current classification was not produced by the source-coordinate replay",
    )

    rows = list(recomputation.get("mismatches", []))
    keys = {(row["leaf_id"], row["field"]) for row in rows}
    _require(
        len(rows) == 147 and len(keys) == 147,
        "current recomputation is not 147 unique mismatch slots",
    )
    _require(_leaf_count(rows) == 39, "current recomputation is not 39 leaves")

    post_rows = post_rc02["inventory"]["remaining_mismatches"]  # type: ignore[index]
    post_slots = {
        (row["leaf_id"], row["field"], row["sto_minus_source_seconds"])
        for row in post_rows
    }
    current_slots = {
        (row["leaf_id"], row["field"], row["sto_minus_source_seconds"])
        for row in rows
    }
    _require(
        current_slots == post_slots,
        "current recomputation does not reconcile the verified 147-slot production result",
    )
    current_basis = recomputation["production_basis"]  # type: ignore[index]
    post_verification = post_rc02["verification"]  # type: ignore[index]
    _require(
        current_basis["projection_sha256"]
        == post_verification["production_projection_sha256"],
        "current production projection does not match the verified post-RC02 result",
    )
    _require(
        current_basis["remaining_keyset_sha256"]
        == post_verification["production_remaining_keyset_sha256"],
        "current mismatch key set does not match the verified post-RC02 result",
    )

    by_group = _counts(rows, "diagnostic_group")
    by_field = _counts(rows, "field")
    by_role = _counts(rows, "dependency_role")
    current_roots_by_group: dict[str, list[str]] = {}
    for group_id in sorted(by_group):
        current_roots_by_group[group_id] = sorted(
            {
                str(row["leaf_id"])
                for row in rows
                if row["diagnostic_group"] == group_id
                and row["dependency_role"] in {"FIRST_DIVERGENCE", "COMPOUND"}
            }
        )

    rc01_rows = [row for row in rows if row["diagnostic_group"] == baseline_diag.MULTI_RESOURCE]
    rc03_rows = [row for row in rows if row["diagnostic_group"] == baseline_diag.ELAPSED_FLOAT]
    rc04_rows = [row for row in rows if row["diagnostic_group"] == baseline_diag.COMPOUND_FLOAT]
    rc01_historical = _group(historical, baseline_diag.MULTI_RESOURCE)
    rc03_historical = _group(historical, baseline_diag.ELAPSED_FLOAT)
    rc04_historical = _group(historical, baseline_diag.COMPOUND_FLOAT)
    root_context = recomputation["root_activity_context"]  # type: ignore[index]
    expected_root_shape = {
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
    rc01_roots = current_roots_by_group.get(baseline_diag.MULTI_RESOURCE, [])
    for leaf_id in rc01_roots:
        observed_shape = {key: root_context[leaf_id].get(key) for key in expected_root_shape}
        _require(
            observed_shape == expected_root_shape,
            f"current RC01 root shape is outside the matrix contract for {leaf_id}",
        )

    historical_rc04_keys = {
        (row["leaf_id"], row["field"])
        for row in historical["mismatches"]  # type: ignore[index]
        if row["diagnostic_group"] == baseline_diag.COMPOUND_FLOAT
    }
    reclassified_rc04 = [
        {
            "leaf_id": row["leaf_id"],
            "field": row["field"],
            "current_group": row["diagnostic_group"],
            "current_role": row["dependency_role"],
            "current_paths": row["dependency_paths"],
        }
        for row in rows
        if (row["leaf_id"], row["field"]) in historical_rc04_keys
    ]

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
                "production_correction_commit": post_rc02["basis"]["production_correction_commit"],  # type: ignore[index]
            },
            "classification_lineage": (
                "post-RC02 labels are comparison-only; current group, role, path and driver "
                "fields come exclusively from current production replay"
            ),
        },
        "current_recomputation": recomputation,
        "current_inventory": {
            "slots": len(rows),
            "leaves": _leaf_count(rows),
            "by_group": by_group,
            "by_field": by_field,
            "by_role": by_role,
            "root_leaf_ids_by_group": current_roots_by_group,
            "rc02_slots": by_group.get(baseline_diag.INACTIVE_BOUNDARY, 0),
        },
        "rc01_review": {
            "classification": "CURRENT_RECOMPUTATION_STRONG_CANDIDATE",
            "historical_name": rc01_historical["name"],
            "current_slots": len(rc01_rows),
            "current_leaves": _leaf_count(rc01_rows),
            "current_by_field": _counts(rc01_rows, "field"),
            "current_by_role": _counts(rc01_rows, "dependency_role"),
            "root_leaf_count": len(rc01_roots),
            "root_leaf_ids": rc01_roots,
            "root_shape": {
                "all_roots_match": True,
                "assignment_count": 2,
                "resource_calendar_count": 2,
                "calendar_class": "resource_calendar_union",
                "assumption_code": "ACTIVITY_RESOURCE_CALENDARS_UNITED",
            },
            "causal_confidence": "STRONG_CANDIDATE",
            "replacement_semantics_status": "NOT_ESTABLISHED",
            "boiler_counterfactual_authorized": False,
            "production_correction_authorized": False,
        },
        "rc03_review": {
            "classification": "CURRENT_RECOMPUTATION_PROVEN_ORIGIN_REMAINS",
            "historical_name": rc03_historical["name"],
            "current_slots": len(rc03_rows),
            "current_leaves": _leaf_count(rc03_rows),
            "root_leaf_ids": current_roots_by_group.get(baseline_diag.ELAPSED_FLOAT, []),
            "causal_confidence": "PROVEN",
            "replacement_semantics_status": "NOT_ESTABLISHED",
            "production_correction_authorized": False,
        },
        "rc04_review": {
            "classification": "HISTORICAL_COMPOUND_SLOT_RECLASSIFIED_BY_CURRENT_REPLAY",
            "historical_name": rc04_historical["name"],
            "historical_slots": len(historical_rc04_keys),
            "current_slots": len(rc04_rows),
            "reclassified_slots": reclassified_rc04,
            "independent_fix_authorized": False,
        },
        "next_experiment": {
            "id": "P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1",
            "status": "EXACT_INPUT_COMMITTED_NATIVE_RETURN_REQUIRED",
            "input": {
                "path": "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V1.xml",
                "bytes": rc01_generate.INPUT_BYTES,
                "sha256": rc01_generate.INPUT_SHA256,
                "project_guid": rc01_generate.PROJECT_GUID,
                "project_start": rc01_generate.PROJECT_START,
            },
            "fixed_inputs": {
                "project_calendar": {
                    "uid": 1,
                    "working_intervals": [["08:00:00", "12:00:00"], ["13:00:00", "17:00:00"]],
                },
                "task_type": "FIXED_UNITS (MSPDI Type 0)",
                "task_duration": rc01_generate.TASK_DURATION,
                "effort_driven": False,
                "ignore_resource_calendar": False,
                "task_calendar": None,
                "manual": False,
                "constraint": "ASAP",
                "progress": "none",
                "levelling": "non-participating: resource CanLevel 0; task delays zero",
                "assignment_work": rc01_generate.ASSIGNMENT_WORK,
                "assignment_units": rc01_generate.ASSIGNMENT_UNITS,
                "assignment_order": list(rc01_generate.ASSIGNMENT_ORDER),
                "topology": "four independent tasks; no relationships",
            },
            "cases": {
                "A": "AM 08:00-12:00 then PM 13:00-17:00 assignment declarations",
                "B": "semantic twin of A with PM then AM declaration order",
                "C": "two distinct resource calendars, both 08:00-12:00",
                "D": "one AM 08:00-12:00 resource assignment",
            },
            "importer_contract": {
                "assignment_work_units_start_finish": "canonical fields",
                "resource_calendar_identity": "canonical field",
                "task_type": "canonical DurationType fixed_units",
                "effort_driven": "raw value preserved as opaque extension; canonical false semantic",
                "ignore_resource_calendar": "raw value preserved as opaque extension; clear maps to canonical false semantic",
            },
            "analyzer": "scripts/evidence/p1_g2_rc01_assignment_native.py",
            "analyzer_contract": {
                "input_validation": "identity, calendars, task settings, duration/start/topology, assignment Work/Units/order all fail closed",
                "support": "all assignment spans fit their resource calendars; A/B task spans equal assignment envelopes and are order-independent; C/D controls pass; A/B differ from union placement",
                "rejection": "controls and order twin pass but A/B do not equal their assignment envelopes",
                "inconclusive": "any invalid control, order effect or mixed result",
            },
            "native_return_required": True,
            "boiler_counterfactual_authorized": False,
            "production_correction_authorized": False,
            "stopping_rule": (
                "only ASSIGNMENT_ENVELOPE_SUPPORTED authorizes a later diagnostic-only "
                "BOILER counterfactual; no native outcome directly authorizes production"
            ),
        },
        "decision": {
            "p1_g2_closed": False,
            "p1_gate": "4/5 IN PROGRESS",
            "p2_started": False,
            "next_action": (
                "run the exact committed synthetic RC01 matrix in Microsoft Project and "
                "return the recalculated XML; do not change production scheduling semantics"
            ),
        },
    }


def build_record(baseline_path: Path) -> dict[str, object]:
    historical, post_rc02 = load_inputs()
    return review_documents(historical, post_rc02, recompute_current(baseline_path))


def serialize(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def refuse_output_alias(output: Path, sources: Mapping[str, Path]) -> None:
    output_resolved = output.resolve(strict=False)
    for role, source in sources.items():
        same_path = output_resolved == source.resolve(strict=False)
        same_object = False
        if output.exists() or output.is_symlink():
            try:
                same_object = output.samefile(source)
            except FileNotFoundError:
                same_object = False
            except OSError as error:
                raise EvidenceError(
                    f"cannot establish whether output aliases {role}"
                ) from error
        if same_path or same_object:
            raise EvidenceError(f"output aliases {role}; evidence inputs are immutable")


def write_output_safely(
    output: Path,
    payload: str,
    sources: Mapping[str, Path],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    refuse_output_alias(output, sources)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        refuse_output_alias(output, sources)
        os.replace(temporary, output)
        temporary = None
        directory_descriptor = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as error:
        raise EvidenceError(f"cannot safely publish evidence output: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--check", type=Path)
    destination.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    protected = {
        "BOILER baseline": args.baseline,
        "historical root-cause evidence": HISTORICAL_PATH,
        "post-RC02 production evidence": POST_RC02_PATH,
    }
    if args.output is not None:
        refuse_output_alias(args.output, protected)
    if args.check is not None:
        refuse_output_alias(args.check, protected)
    payload = serialize(build_record(args.baseline))
    if args.check is not None:
        if args.check.read_bytes() != payload.encode("utf-8"):
            print(f"{args.check} does not match the current post-RC02 replay", file=sys.stderr)
            return 1
        return 0
    if args.output is not None:
        write_output_safely(args.output, payload, protected)
        return 0
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
