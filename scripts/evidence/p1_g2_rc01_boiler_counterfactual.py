#!/usr/bin/env python3
"""Predeclared diagnostic RC01 assignment-envelope counterfactual.

Never writes or patches production source. The two pass placement functions are
temporarily wrapped during a single, synchronous diagnostic calculation; all
other production bounds, relationships, progress and float rules are reused.
The raw BOILER oracle is read only after its exact byte identity is checked.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
for root in (ROOT, ROOT / "src"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts.evidence import p1_g2_baseline_diagnostics as baseline
from scripts.evidence import p1_g2_post_rc02_review as current
from scripts.evidence import p1_g2_rc01_assignment_native_v2_generate as matrix
from scripts.evidence import p1_g2_rc02_boiler_counterfactual as prior
from scripts.evidence import p1_g2_rc02_production_verification as production
from sto.core.calendar.arithmetic import earliest_span, latest_span
from sto.core.engine import float_analysis
from sto.core.engine.plan import build_plan
from sto.core.engine.validate import validate_result
from sto.core.model.enums import ActivityKind, DurationType

forward = importlib.import_module("sto.core.engine.forward")
backward = importlib.import_module("sto.core.engine.backward")

PROFILE = "sto-diagnostic-p1-g2-rc01-assignment-envelope-v1"
SCHEMA = "sto-p1-g2-rc01-boiler-counterfactual-predeclared-v1"
BASE_SHA = "e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70"
BASE_BYTES = 3_361_935
CURRENT_PATH = ROOT / "docs/evidence/p1-g2-post-rc02-review-2026-09-25.json"
CURRENT_SHA = "9a3ef68637b6e213188400f05fdca9bd216eebfbafa100f10f817623f5b8f3d3"
NATIVE_PATH = ROOT / "docs/evidence/p1-g2-rc01-native-v2-valid-return-2026-09-28.json"
NATIVE_SHA = "71702adb09f08014c8ce14bed7651162bff65787f8d4d4945bb2383710ca6a6c"
ROOTS = frozenset(("L0070", "L0075", "L0080", "L0083", "L0084", "L0114",
                   "L0127", "L0148", "L0157", "L0190"))
FIELDS = tuple(baseline.RESULT_FIELDS)


class CounterfactualError(ValueError):
    """An input or network shape lies outside the predeclared diagnostic."""


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def pinned(path: Path, size: int | None, sha: str) -> bytes:
    payload = path.read_bytes()
    if (size is not None and len(payload) != size) or digest(payload) != sha:
        raise CounterfactualError(f"pinned evidence identity differs: {path.name}")
    return payload


def load_contract() -> tuple[dict, dict]:
    inventory = json.loads(pinned(CURRENT_PATH, None, CURRENT_SHA))
    v2 = json.loads(pinned(NATIVE_PATH, None, NATIVE_SHA))
    rows = inventory["current_recomputation"]["mismatches"]
    keys = {(row["leaf_id"], row["field"]) for row in rows}
    if (len(rows), len(keys), inventory["current_inventory"]["leaves"]) != (147, 147, 39):
        raise CounterfactualError("current 147-slot inventory changed")
    if inventory["current_inventory"]["by_group"] != {"G2-RC01": 144, "G2-RC03": 3}:
        raise CounterfactualError("current root families changed")
    if set(inventory["current_inventory"]["root_leaf_ids_by_group"]["G2-RC01"]) != ROOTS:
        raise CounterfactualError("current RC01 roots changed")
    if (v2["classification"]["verdict"] != "V2_ASSIGNMENT_ENVELOPE_SUPPORTED"
        or not all(v2["classification"]["predicates"].values())
        or v2["native_return"] != {"bytes": 54152, "sha256":
                                     "674b2a70649991ac6b9624ced1d16ca88a5287fed35da08486a59986360d513e"}
        or v2["decision"]["production_correction_authorized"]):
        raise CounterfactualError("V2 evidence does not authorize this diagnostic")
    if matrix.INPUT_SHA256 != "f8c0b622e257186ee30c6b933aedebe697841dc41f72b2c3137ba0f77126cb0c":
        raise CounterfactualError("V2 generated input identity changed")
    pinned(ROOT / "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2.xml",
           matrix.INPUT_BYTES, matrix.INPUT_SHA256)
    return inventory, v2


def source_id(entity) -> str:
    ids = [ref.uid for ref in entity.external_refs if ref.system.value == "MicrosoftProject"]
    if len(ids) != 1:
        raise CounterfactualError("missing or ambiguous Microsoft Project UID")
    return ids[0]


def _assignment_spec(schedule, plan, activity):
    """Exact fixed-units work/units conversion; no rounding or date inputs."""
    rows = [a for a in schedule.assignments if a.activity_uid == activity.uid]
    if len(rows) < 2:
        return None, "fewer than two assignments"
    if (activity.kind != ActivityKind.TASK or not activity.active or activity.manual
        or activity.actual_start is not None or activity.actual_finish is not None
        or activity.duration_type != DurationType.FIXED_UNITS or activity.effort_driven
        or activity.calendar_uid is not None
        or activity.source_fields.get("ignore_resource_calendar_source") == "1"
        or activity.primary_constraint not in (None,)
        or activity.secondary_constraint is not None
        or activity.levelling_delay_seconds
        or activity.planned_duration is None or activity.planned_duration.elapsed
        or activity.remaining_duration not in (None, activity.planned_duration)):
        return None, "task flags, duration, progress or calendar outside bounded rule"
    resources = {r.uid: r for r in schedule.resources}
    result = []
    for a in rows:
        r = resources.get(a.resource_uid)
        if (r is None or r.calendar_uid not in plan.calendars or a.unassigned_placeholder
            or a.work.actual_seconds or a.percent_work_complete_permille
            or a.work.budgeted_seconds <= 0 or a.work.remaining_seconds != a.work.budgeted_seconds
            or a.units.budgeted_permille <= 0):
            return None, "assignment identity, Work, Units or progress outside bounded rule"
        numerator = a.work.budgeted_seconds * 1000
        if numerator % a.units.budgeted_permille:
            return None, "assignment Work/Units requires fractional seconds"
        result.append((a, r, plan.calendars[r.calendar_uid].intervals,
                       numerator // a.units.budgeted_permille))
    if len({r.calendar_uid for _, r, _, _ in result}) < 2:
        return None, "only one distinct resource calendar"
    return tuple(result), None


def applicability(schedule, plan, roots: frozenset[str] = ROOTS):
    leaf_by_uid, uid_by_leaf, _ = prior._leaf_maps(schedule)
    missing = roots - set(uid_by_leaf)
    if missing:
        raise CounterfactualError(f"missing current roots: {sorted(missing)}")
    incoming = plan.network.predecessors()
    outgoing = plan.network.successors()
    specs = {}
    audit = []
    assumptions = {}
    for row in plan.assumed:
        assumptions.setdefault(row.uid, []).append(row.code)
    for leaf in sorted(roots):
        uid = uid_by_leaf[leaf]
        activity = next(a for a in schedule.activities if a.uid == uid)
        assigned = [a for a in schedule.assignments if a.activity_uid == uid]
        resources = {r.uid: r for r in schedule.resources}
        spec, reason = _assignment_spec(schedule, plan, activity) if uid in plan.network.activity_by_uid() else (None, "not scheduled")
        if spec is not None:
            specs[uid] = spec
        # V2's native observation has exactly two four-hour, 100% assignments,
        # an unprogressed four-hour fixed-units task and no network edges.
        within = (
            (spec is not None and len(spec) == 2 and not incoming[uid]
             and not outgoing[uid] and activity.planned_duration.seconds == 14400
             and all(d == 14400 and a.units.budgeted_permille == 1000
                     for a, _, _, d in spec))
            or (spec is None and len(assigned) == 1 and reason == "fewer than two assignments"
                and activity.planned_duration is not None
                and activity.planned_duration.seconds == 14400
                and assigned[0].work.budgeted_seconds == 14400
                and assigned[0].units.budgeted_permille == 1000
                and not incoming[uid] and not outgoing[uid]
                and activity.kind == ActivityKind.TASK and activity.active
                and not activity.manual and activity.duration_type == DurationType.FIXED_UNITS
                and not activity.effort_driven and activity.calendar_uid is None
                and activity.actual_start is None and activity.actual_finish is None)
        )
        audit.append({
            "leaf_id": leaf, "kind": activity.kind.value, "active": activity.active,
            "manual": activity.manual,
            "progress_state": "complete" if activity.actual_finish else "started" if activity.actual_start else "not_started",
            "constraint": None if activity.primary_constraint is None else activity.primary_constraint.type.value,
            "task_type": activity.duration_type.value,
            "planned_duration_seconds": None if activity.planned_duration is None else activity.planned_duration.seconds,
            "remaining_duration_seconds": None if activity.remaining_duration is None else activity.remaining_duration.seconds,
            "effort_driven": activity.effort_driven,
            "ignore_resource_calendar": activity.source_fields.get("ignore_resource_calendar_source") == "1",
            "task_calendar_uid": None if activity.calendar_uid is None else source_id(next(c for c in schedule.calendars if c.uid == activity.calendar_uid)),
            "assignment_count": len(assigned),
            "resource_count": len({a.resource_uid for a in assigned}),
            "distinct_resource_calendar_count": len({resources[a.resource_uid].calendar_uid for a in assigned if a.resource_uid in resources}),
            "assignments": [{"assignment_uid": source_id(a),
                             "resource_uid": None if a.resource_uid not in resources else source_id(resources[a.resource_uid]),
                             "calendar_uid": None if a.resource_uid not in resources or resources[a.resource_uid].calendar_uid is None else source_id(next(c for c in schedule.calendars if c.uid == resources[a.resource_uid].calendar_uid)),
                             "work_seconds": a.work.budgeted_seconds,
                             "units_permille": a.units.budgeted_permille}
                            for a in assigned],
            "predecessors": [{"leaf_id": leaf_by_uid[e.predecessor_uid], "type": e.type.value, "lag_seconds": e.lag} for e in incoming[uid]],
            "successors": [{"leaf_id": leaf_by_uid[e.successor_uid], "type": e.type.value, "lag_seconds": e.lag} for e in outgoing[uid]],
            "assumption_codes": sorted(assumptions.get(uid, [])),
            "classification": "WITHIN_V2_COUNTERFACTUAL_BOUNDARY" if within else "DIAGNOSTIC_EXTRAPOLATION_REQUIRED",
            "diagnostic_eligible": spec is not None,
            "reason": None if within else reason or "task/assignment Work, duration or topology outside V2 matrix",
        })
    return specs, audit


@contextmanager
def _placement(specs):
    old_forward, old_backward = forward._place, backward._place

    def early(activity, duration, start_bound, finish_bound, horizon, snap, pinned, coordinate):
        if activity.uid not in specs:
            return old_forward(activity, duration, start_bound, finish_bound,
                               horizon, snap, pinned, coordinate)
        if pinned is not None or duration != activity.duration:
            raise CounterfactualError("diagnostic envelope cannot place constrained or progressed work")
        spans = [earliest_span(cal, start_bound, start_bound, work, horizon)
                 for _, _, cal, work in specs[activity.uid]]
        if any(span is None for span in spans):
            raise CounterfactualError("assignment exceeds compiled forward horizon")
        result = (min(span[0] for span in spans), max(span[1] for span in spans))
        if result[1] < finish_bound:
            raise CounterfactualError("finish-side lower bound needs an unmeasured envelope rule")
        return result

    def late(activity, duration, start_bound, finish_bound, snap, pinned, coordinate):
        if activity.uid not in specs:
            return old_backward(activity, duration, start_bound, finish_bound,
                                snap, pinned, coordinate)
        if pinned is not None or duration != activity.duration:
            raise CounterfactualError("diagnostic envelope cannot invert constrained or progressed work")
        spans = [latest_span(cal, start_bound, finish_bound, work, cal.first or 0)
                 for _, _, cal, work in specs[activity.uid]]
        if any(span is None for span in spans):
            raise CounterfactualError("assignment exceeds compiled backward floor")
        result = (min(span[0] for span in spans), max(span[1] for span in spans))
        if result[0] > start_bound or result[1] > finish_bound:
            raise CounterfactualError("assignment envelope violates late bound")
        return result

    forward._place = early
    backward._place = late
    try:
        yield
    finally:
        forward._place = old_forward
        backward._place = old_backward


def calculate(schedule, *, include: frozenset[str] | None = None):
    """Calculate independent early/late/float; never reads source output dates."""
    if schedule.project.start is None:
        raise CounterfactualError("project start is absent")
    start = schedule.project.start
    plan = build_plan(schedule, (start - timedelta(days=90), start + timedelta(days=365)))
    leaves, _, _ = prior._leaf_maps(schedule)
    roots = frozenset(leaves.values()) if include is None else include
    specs, audit = applicability(schedule, plan, roots)
    with _placement(specs):
        early = forward.forward_pass(plan.network, snap_milestones=plan.snap_milestones,
                                     progress_policy=plan.progress_policy)
        late = backward.backward_pass(plan.network, early,
                                       snap_milestones=plan.snap_milestones,
                                       progress_policy=plan.progress_policy)
    floats = float_analysis(plan.network, early, late, threshold=plan.critical_float_threshold)
    results = {}
    for uid in plan.network.activity_by_uid():
        e, l, f = early.by_uid()[uid], late.by_uid()[uid], floats.by_uid()[uid]
        results[uid] = (plan.to_datetime(e.early_start), plan.to_datetime(e.early_finish),
                        plan.to_datetime(e.early_start), plan.to_datetime(e.early_finish),
                        plan.to_datetime(l.late_start), plan.to_datetime(l.late_finish),
                        f.total_float, f.free_float, f.critical)
    return plan, early, late, floats, results, audit


def validate_diagnostic(schedule, plan, early, late, floats, audit) -> list[str]:
    """Use the production validator, replacing only the envelope length rule.

    The production validator expects the task to consume its declared duration
    on the union calendar; that check cannot validate an assignment envelope.
    For each eligible task independently regenerate the assignment early and
    late spans on their own calendars and check both task envelopes exactly.
    Every other production validation code remains a refusal.
    """
    codes = []
    by_leaf = prior._leaf_maps(schedule)[1]
    eligible = {by_leaf[row["leaf_id"]] for row in audit if row["diagnostic_eligible"]}
    for violation in validate_result(plan.network, early, late, floats):
        if not (violation.uid in eligible and violation.code in
                {"EARLY_SPAN_WRONG_LENGTH", "LATE_SPAN_WRONG_LENGTH"}):
            codes.append(violation.code)
    rows = {a.uid: a for a in schedule.activities}
    for uid in eligible:
        specs, reason = _assignment_spec(schedule, plan, rows[uid])
        if specs is None:
            codes.append("DIAGNOSTIC_ELIGIBILITY_CHANGED:" + str(reason))
            continue
        e, l = early.by_uid()[uid], late.by_uid()[uid]
        before = [earliest_span(calendar, e.early_start, e.early_start, work, plan.network.horizon)
                  for _, _, calendar, work in specs]
        after = [latest_span(calendar, l.late_finish, l.late_finish, work, calendar.first or 0)
                 for _, _, calendar, work in specs]
        if any(span is None for span in before + after):
            codes.append("ASSIGNMENT_SPAN_UNREACHABLE")
            continue
        if (min(span[0] for span in before), max(span[1] for span in before)) != (e.early_start, e.early_finish):
            codes.append("EARLY_ASSIGNMENT_ENVELOPE_INVALID")
        if (min(span[0] for span in after), max(span[1] for span in after)) != (l.late_start, l.late_finish):
            codes.append("LATE_ASSIGNMENT_ENVELOPE_INVALID")
    return sorted(codes)


def pre_result_identity() -> dict[str, str | int]:
    path = Path(__file__).relative_to(ROOT).as_posix()
    commit = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", path], cwd=ROOT, text=True,
    ).strip()
    if len(commit) != 40:
        raise CounterfactualError("no committed pre-result tool")
    committed = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
    current_bytes = Path(__file__).read_bytes()
    if committed != current_bytes:
        raise CounterfactualError("tool differs from pre-result commit")
    return {"commit": commit, "tool_path": path,
            "tool_bytes": len(committed), "tool_sha256": digest(committed)}


def build_record(source: Path) -> dict:
    tool_identity = pre_result_identity()
    inventory, v2 = load_contract()
    raw = pinned(source, BASE_BYTES, BASE_SHA)
    before = source.read_bytes()
    # Recompute and compare the *whole* current production/root record before
    # allowing the candidate to observe any Project dates as an oracle.
    verified = current.build_record(source)
    if current.serialize(verified).encode() != CURRENT_PATH.read_bytes():
        raise CounterfactualError("current production does not reproduce pinned 147-slot record")
    schedule = baseline._load(raw)
    plan, early, late, floats, result, audit = calculate(schedule, include=ROOTS)
    source_by_uid = {row.uid: baseline._source_uid(row) for row in schedule.activities}
    candidate = {source_by_uid[uid]: value for uid, value in result.items()}
    observed = baseline._observed(baseline._activities(schedule))
    _, _, source_by_leaf = prior._leaf_maps(schedule)
    leaf_by_source = {v: k for k, v in source_by_leaf.items()}
    candidate_projection, _ = production._projection(candidate, leaf_by_source)
    candidate_fingerprint = digest(PROFILE.encode() + b"\0"
                                   + tool_identity["tool_sha256"].encode() + b"\0"
                                   + candidate_projection)
    before_rows = verified["current_recomputation"]["mismatches"]
    initial = {(r["leaf_id"], r["field"]) for r in before_rows}
    after = prior._mismatch_keys(observed, candidate, leaf_by_source)
    if len(initial) != 147:
        raise CounterfactualError("initial mismatch keys are not exactly 147")
    earlier = baseline._engine(schedule, baseline._calculate(schedule).result)
    if set(candidate) != set(earlier):
        raise CounterfactualError("calculated eligible leaves changed")
    by_key = {(r["leaf_id"], r["field"]): r for r in before_rows}
    rc01 = {k for k in initial if by_key[k]["diagnostic_group"] == "G2-RC01"}
    rc03 = initial - rc01
    def abs_delta(key, rows):
        leaf, field = key
        value = rows[source_by_leaf[leaf]][FIELDS.index(field)]
        oracle = observed[source_by_leaf[leaf]][FIELDS.index(field)]
        return abs(prior._delta(oracle, value))
    improved = {k for k in rc01 & after if abs_delta(k, candidate) < abs_delta(k, earlier)}
    worsened = {k for k in rc01 & after if abs_delta(k, candidate) > abs_delta(k, earlier)}
    other_worsened = {k for k in rc03 & after if abs_delta(k, candidate) > abs_delta(k, earlier)}
    new = after - initial
    closed = rc01 - after
    unsupported = [r["leaf_id"] for r in audit if r["classification"] != "WITHIN_V2_COUNTERFACTUAL_BOUNDARY"]
    violations = validate_diagnostic(schedule, plan, early, late, floats, audit)
    supported = (not unsupported and not violations and len(closed) == 144
                 and not new and not worsened and not other_worsened
                 and after == rc03 and len(after) == 3)
    if supported:
        verdict = "RC01_ASSIGNMENT_ENVELOPE_BOILER_COUNTERFACTUAL_SUPPORTED"
    elif unsupported:
        verdict = "RC01_ASSIGNMENT_ENVELOPE_BOILER_COUNTERFACTUAL_OUTSIDE_NATIVE_BOUNDARY"
    elif (closed or improved) and not worsened and not new and not other_worsened and not violations:
        verdict = "RC01_ASSIGNMENT_ENVELOPE_BOILER_COUNTERFACTUAL_PARTIAL"
    else:
        verdict = "RC01_ASSIGNMENT_ENVELOPE_BOILER_COUNTERFACTUAL_REJECTED"
    if source.read_bytes() != before:
        raise CounterfactualError("BOILER source changed during analysis")
    return {
        "schema": SCHEMA, "profile": PROFILE,
        "production_main": "60313811d6867c28e71cb22bccfd3cc0c8f1618d",
        "source": {"bytes": BASE_BYTES, "sha256": BASE_SHA},
        "starting_inventory_sha256": CURRENT_SHA,
        "v2_evidence_sha256": NATIVE_SHA,
        "v2_native_return": v2["native_return"],
        "pre_result_tool": tool_identity,
        "diagnostic_fingerprint_sha256": candidate_fingerprint,
        "production_projection_sha256": verified["current_recomputation"]["production_basis"]["projection_sha256"],
        "applicability": audit,
        "before": {"slots": len(initial), "rc01": len(rc01), "rc03": len(rc03),
                   "keys": sorted([list(k) for k in initial])},
        "after": {"slots": len(after), "rc01_remaining": len(rc01 & after),
                  "rc03_remaining": len(rc03 & after), "keys": sorted([list(k) for k in after])},
        "movement": {"rc01_closed": len(closed), "rc01_improved": len(improved),
                     "rc01_unchanged": len(rc01 & after - improved - worsened),
                     "rc01_worsened": len(worsened), "other_worsened": len(other_worsened),
                     "new_keys": sorted([list(k) for k in new])},
        "validator": {"profile": PROFILE, "violations": violations},
        "decision": {"classification": verdict,
                     "production_rc01_correction_authorized": supported},
    }


def protected_sources(boiler: Path) -> dict[str, Path]:
    """Every immutable input read by this tool or cited as its preregistration."""
    evidence = ROOT / "docs/evidence"
    return {
        "BOILER baseline": boiler,
        "diagnostic tool": Path(__file__),
        "current root evidence": CURRENT_PATH,
        "V2 native evidence": NATIVE_PATH,
        "frozen V2 input": ROOT / "tests/fixtures/P1-G2-RC01-ASSIGNMENT-ENVELOPE-NATIVE-MATRIX-V2.xml",
        "V2 contract": evidence / "p1-g2-rc01-native-v2-contract-2026-09-28.md",
        "V2 return receipt": evidence / "p1-g2-rc01-native-v2-return-2026-09-28.md",
        "predeclared contract": evidence / "p1-g2-rc01-boiler-counterfactual-predeclared-2026-09-28.json",
        "predeclared explanation": evidence / "p1-g2-rc01-boiler-counterfactual-predeclared-2026-09-28.md",
        "first pre-result identity": evidence / "p1-g2-rc01-boiler-counterfactual-pre-result-identity-2026-09-28.json",
        "current pre-result identity": evidence / "p1-g2-rc01-boiler-counterfactual-pre-result-identity-v2-2026-09-28.json",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("boiler", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    sources = protected_sources(args.boiler)
    if args.output is not None:
        current.refuse_output_alias(args.output, sources)
    record = build_record(args.boiler)
    data = json.dumps(record, sort_keys=True, indent=2) + "\n"
    if args.output is None:
        print(data, end="")
    else:
        current.write_output_safely(args.output, data, sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
