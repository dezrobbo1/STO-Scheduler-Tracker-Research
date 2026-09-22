#!/usr/bin/env python3
"""Classify the fixed P1-G2 BOILER baseline mismatch families.

This is evidence tooling, not scheduler policy.  It consumes the two exact
external fixtures from the clean UID 227 controlled repeat, reproduces the
fixed nine-field comparison, then traces each static baseline mismatch through
the production engine's actual or source-coordinate replay driver.

The replay changes no production input or formula.  It substitutes Project's
stored predecessor/successor coordinates at one calculation boundary and asks
the existing placement primitives whether the current row then agrees.  A
match is propagation evidence; a remaining difference is a first divergence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Iterable, Mapping, Sequence
from uuid import UUID


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
_EVIDENCE_TOOL_BYTES_AT_STARTUP = Path(__file__).resolve().read_bytes()

# Evidence generation must execute checkout source, never pre-existing bytecode.
# Redirect importlib's cache lookup to a fresh private directory before any
# repository module is imported, then disable cache writes. This makes both
# ordinary __pycache__ entries and caller-supplied PYTHONPYCACHEPREFIX caches
# irrelevant to the production code that generates the record.
_EVIDENCE_PYCACHE_DIRECTORY = tempfile.TemporaryDirectory(
    prefix="sto-p1-g2-pycache-"
)
sys.pycache_prefix = _EVIDENCE_PYCACHE_DIRECTORY.name
sys.dont_write_bytecode = True

# Use this checkout's classifier and production implementation even when a
# caller supplied the same paths later in PYTHONPATH.  Merely checking for
# membership would leave an earlier shadow package able to perform a
# calculation attributed to this repository's verified production tree.
_CHECKOUT_IMPORT_ROOTS = [str(ROOT), str(SRC)]
sys.path[:] = [
    entry for entry in sys.path if entry not in _CHECKOUT_IMPORT_ROOTS
]
sys.path[:0] = _CHECKOUT_IMPORT_ROOTS

from tests.controlled_native_progress_evidence import (  # noqa: E402
    BASELINE_MISMATCH,
    ENGINE_NATIVE_AGREEMENT,
    EXPLICIT_EXCLUSION,
    RESULT_FIELDS,
    UNCHANGED,
    classify_controlled_transition,
    unique_rows,
)

from sto.core.calendar.arithmetic import latest_span, prev_working_start  # noqa: E402
from sto.core.engine import (  # noqa: E402
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
)
from sto.core.engine.backward import (  # noqa: E402
    ActivityLateTimes,
    _bounds as backward_bounds,
    _driver as backward_driver,
    _place as backward_place,
)
from sto.core.engine.criticality import signed_working  # noqa: E402
from sto.core.engine.forward import (  # noqa: E402
    ActivityTimes,
    _bounds as forward_bounds,
    _driver as forward_driver,
    _place as forward_place,
)
from sto.core.engine.network import lag_calendar_for, unshift_lag  # noqa: E402
from sto.core.engine.progress import ProgressState  # noqa: E402
from sto.core.model.enums import ConstraintType  # noqa: E402
from sto.core.model.migrate.sto_v011 import migrate  # noqa: E402
from sto.legacy import import_mspdi  # noqa: E402


SCHEMA = "sto-p1-g2-baseline-root-causes-v3"
EVIDENCE_DATE = "2026-09-22"
REPOSITORY_BASE = "0805bcb44f5122e9499e1dc2449dc25ee6b01abd"
PRODUCTION_BASIS_PATHS = (
    "src/sto/core",
    "src/sto/legacy",
    "tests/controlled_native_progress_evidence.py",
)
PRODUCTION_BASIS_PATH_TREE_SHA256 = (
    "483477d8e28d644327e98ad378bbdba00f572d2f941e1e36f075f02003fb81c2"
)
TOOL_PATH = "scripts/evidence/p1_g2_baseline_diagnostics.py"
BASELINE_IDENTITY = (
    3_361_935,
    "e9b9b7994cc5cc50479807b82c452da742a91de9f7de52b172a6be6f4f399c70",
)
REPEAT_IDENTITY = (
    3_362_778,
    "6e0e5321ecadf4b8d9e96685968112803975737a61444104b45ae8cfa522df66",
)
TARGET_SOURCE_UID = "227"
TARGET_ACTUAL_START = datetime.fromisoformat("2026-09-14T11:00:00")
TARGET_REMAINING_SECONDS = 14_400
TARGET_BUILD = "16.0.20228.20186"

EXPECTED_CLASSIFICATIONS = {
    UNCHANGED: 3_594,
    BASELINE_MISMATCH: 422,
    ENGINE_NATIVE_AGREEMENT: 43,
    EXPLICIT_EXCLUSION: 81,
}
EXPECTED_BY_FIELD = {
    "start": 62,
    "finish": 67,
    "early_start": 62,
    "early_finish": 67,
    "late_start": 42,
    "late_finish": 33,
    "total_float": 71,
    "free_float": 16,
    "critical": 2,
}

MULTI_RESOURCE = "G2-RC01"
INACTIVE_BOUNDARY = "G2-RC02"
ELAPSED_FLOAT = "G2-RC03"
COMPOUND_FLOAT = "G2-RC04"
UNKNOWN = "G2-UNKNOWN"
DEPENDENCY_ROLES = {
    "ROOT": "FIRST_DIVERGENCE",
    "PROPAGATED": "DEPENDENT",
    "COMPOUND": "COMPOUND",
    "DERIVED": "DERIVED",
}

GROUP_DEFINITIONS = {
    MULTI_RESOURCE: {
        "status": "STRONG_CANDIDATE",
        "causal_confidence": "STRONG_CANDIDATE",
        "name": "multi-resource calendar-union approximation",
        "semantic": (
            "The first divergences coincide with activities whose stored task span equals "
            "the stored assignment-span envelope while STO uses its documented union of "
            "resource calendars."
        ),
        "mechanical_grouping_basis": (
            "First-divergence rows carry ACTIVITY_RESOURCE_CALENDARS_UNITED; source-"
            "coordinate replay closes the dependent rows assigned to this family."
        ),
        "causal_confidence_basis": (
            "The shape and stored assignment arithmetic strongly identify this semantic, "
            "but no independent assignment-driven counterfactual has removed the root "
            "divergence."
        ),
        "replacement_semantics_status": "NOT_ESTABLISHED",
        "classification": "KNOWN-ASSUMPTION",
        "existing_codes": ["ACTIVITY_RESOURCE_CALENDARS_UNITED"],
        "inside_claimed_p1_supported_envelope": False,
        "production_correction_justified": False,
        "next_experiment": (
            "Define an assignment-driven canonical scheduling contract and an independent "
            "oracle before replacing the documented calendar-union approximation."
        ),
    },
    INACTIVE_BOUNDARY: {
        "status": "STRONG_CANDIDATE",
        "causal_confidence": "STRONG_CANDIDATE",
        "name": "inactive-activity logic boundary",
        "semantic": (
            "The first divergences occur on active rows adjacent to relationships removed "
            "with inactive endpoints; the stored Project coordinates retain effects on "
            "active rows on both sides of those inactive rows."
        ),
        "mechanical_grouping_basis": (
            "First divergences occur at inactive endpoint boundaries; source-coordinate "
            "replay closes dependent date rows and isolates predecessor Free Slack residuals."
        ),
        "causal_confidence_basis": (
            "Adjacency and replay make this the strongest candidate, but no native causal "
            "experiment has established the inactive-row rule that removes both forward "
            "and late/free-float divergences."
        ),
        "replacement_semantics_status": "NOT_ESTABLISHED",
        "classification": "KNOWN-ASSUMPTION",
        "existing_codes": [
            "ACTIVITY_SUCCESSOR_OF_INACTIVE",
            "RELATIONSHIP_ENDPOINT_NOT_SCHEDULED",
        ],
        "inside_claimed_p1_supported_envelope": False,
        "production_correction_justified": False,
        "next_experiment": (
            "Use a minimal native Project matrix around active-to-inactive-to-active FS "
            "chains; the already-tried zero-duration pass-through rule worsened BOILER."
        ),
    },
    ELAPSED_FLOAT: {
        "status": "PROVEN",
        "causal_confidence": "PROVEN",
        "name": "elapsed-duration float basis",
        "semantic": (
            "On both BOILER elapsed rows the stored TotalSlack and FreeSlack equal elapsed "
            "coordinate gaps, while production measures float as working time."
        ),
        "mechanical_grouping_basis": (
            "Source-date float replay leaves only the elapsed-duration rows as direct float "
            "residuals."
        ),
        "causal_confidence_basis": (
            "With identical stored early/late coordinates, elapsed coordinate subtraction "
            "reproduces the source slack while production working-time arithmetic produces "
            "the residual."
        ),
        "replacement_semantics_status": "NOT_ESTABLISHED",
        "classification": "KNOWN-ASSUMPTION",
        "existing_codes": ["ACTIVITY_DURATION_ELAPSED"],
        "inside_claimed_p1_supported_envelope": False,
        "production_correction_justified": False,
        "next_experiment": (
            "Add an independent elapsed-duration float conformance case before carrying an "
            "elapsed-float flag through PlannedActivity and result fingerprints."
        ),
    },
    COMPOUND_FLOAT: {
        "status": "STRONG_CANDIDATE",
        "causal_confidence": "STRONG_CANDIDATE",
        "name": "multi-resource/inactive total-float convergence",
        "semantic": (
            "One Total Float slot consumes an early coordinate assigned to the inactive-"
            "boundary family and a late coordinate assigned to the multi-resource family."
        ),
        "mechanical_grouping_basis": (
            "The Total Float minimum consumes early and late coordinate families assigned "
            "to G2-RC02 and G2-RC01 respectively."
        ),
        "causal_confidence_basis": (
            "Its confidence is capped at STRONG_CANDIDATE because both parent causal "
            "attributions remain candidates."
        ),
        "replacement_semantics_status": "NOT_ESTABLISHED",
        "classification": "EVIDENCE",
        "existing_codes": [
            "ACTIVITY_RESOURCE_CALENDARS_UNITED",
            "ACTIVITY_SUCCESSOR_OF_INACTIVE",
        ],
        "inside_claimed_p1_supported_envelope": False,
        "production_correction_justified": False,
        "next_experiment": "Resolve its two parent causes; it is not an independent fix.",
    },
    UNKNOWN: {
        "status": "UNKNOWN",
        "causal_confidence": "UNKNOWN",
        "name": "unclassified mismatch",
        "semantic": "No defensible causal attribution was established.",
        "mechanical_grouping_basis": "No supported mechanical family was identified.",
        "causal_confidence_basis": "Available evidence does not support attribution.",
        "replacement_semantics_status": "NOT_ESTABLISHED",
        "classification": "UNKNOWN",
        "existing_codes": [],
        "inside_claimed_p1_supported_envelope": None,
        "production_correction_justified": False,
        "next_experiment": "Isolate the first divergence with a bounded replay.",
    },
}


class DiagnosticError(RuntimeError):
    """The fixed evidence contract could not be reproduced or reconciled."""


def _read_evidence_tool_identity(
    path: Path,
    *,
    logical_path: str = TOOL_PATH,
) -> dict[str, object]:
    """Read one immutable identity for the diagnostic source file."""

    try:
        payload = path.read_bytes()
    except OSError as error:
        raise DiagnosticError(f"cannot read evidence tool bytes: {error}") from error
    return {
        "path": logical_path,
        "schema": SCHEMA,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


# The source payload is captured before checkout imports.  The final lineage
# check rereads the path and refuses a concurrent replacement, binding the
# record to the tool bytes present when this process began rather than whichever
# bytes happen to be present when serialization finishes.
_EVIDENCE_TOOL_IDENTITY_AT_STARTUP = {
    "path": TOOL_PATH,
    "schema": SCHEMA,
    "bytes": len(_EVIDENCE_TOOL_BYTES_AT_STARTUP),
    "sha256": hashlib.sha256(_EVIDENCE_TOOL_BYTES_AT_STARTUP).hexdigest(),
}


def _git(
    repository_root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=repository_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:  # pragma: no cover - environment failure
        raise DiagnosticError(f"cannot verify production basis: {error}") from error
    if check and completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise DiagnosticError(
            f"cannot verify production basis with git {' '.join(arguments)}: {detail}"
        )
    return completed


def _worktree_blob_id(
    repository_root: Path,
    relative_path: bytes,
    index_mode: bytes,
    object_format: str,
) -> bytes:
    try:
        path = repository_root / relative_path.decode("utf-8")
        metadata = path.lstat()
        if index_mode == b"120000":
            if not stat.S_ISLNK(metadata.st_mode):
                raise DiagnosticError("production basis file type differs from its index")
            payload = os.fsencode(os.readlink(path))
        elif index_mode in {b"100644", b"100755"}:
            if not stat.S_ISREG(metadata.st_mode):
                raise DiagnosticError("production basis file type differs from its index")
            executable = bool(metadata.st_mode & stat.S_IXUSR)
            if executable != (index_mode == b"100755"):
                raise DiagnosticError("production basis file mode differs from its index")
            payload = path.read_bytes()
        else:
            raise DiagnosticError(
                f"unsupported production basis index mode {index_mode.decode('ascii')}"
            )
    except (OSError, UnicodeError) as error:
        raise DiagnosticError("cannot read production basis worktree bytes") from error
    if object_format == "sha1":
        digest = hashlib.sha1()
    elif object_format == "sha256":
        digest = hashlib.sha256()
    else:
        raise DiagnosticError(f"unsupported git object format {object_format}")
    digest.update(f"blob {len(payload)}\0".encode("ascii"))
    digest.update(payload)
    return digest.hexdigest().encode("ascii")


def verify_production_basis(
    *,
    repository_root: Path = ROOT,
    declared_commit: str = REPOSITORY_BASE,
    production_paths: Sequence[str] = PRODUCTION_BASIS_PATHS,
    expected_path_tree_sha256: str | None = PRODUCTION_BASIS_PATH_TREE_SHA256,
) -> dict[str, object]:
    """Verify that the calculation code matches its declared immutable basis."""

    commit_probe = _git(
        repository_root,
        "cat-file",
        "-e",
        f"{declared_commit}^{{commit}}",
        check=False,
    )
    if commit_probe.returncode == 0:
        declared_tree_entries = _git(
            repository_root,
            "ls-tree",
            "-r",
            "-z",
            declared_commit,
            "--",
            *production_paths,
        ).stdout
        if not declared_tree_entries:
            raise DiagnosticError("declared production basis contains no tracked paths")
        declared_tree_sha256 = hashlib.sha256(declared_tree_entries).hexdigest()
        if expected_path_tree_sha256 is None:
            expected_path_tree_sha256 = declared_tree_sha256
        elif declared_tree_sha256 != expected_path_tree_sha256:
            raise DiagnosticError(
                "declared production basis does not match its pinned path-tree digest"
            )
    elif expected_path_tree_sha256 is None:
        raise DiagnosticError(
            "declared production basis is unavailable and has no pinned path-tree digest"
        )

    index_entries = _git(
        repository_root,
        "ls-files",
        "--stage",
        "-z",
        "--",
        *production_paths,
    ).stdout
    object_format = (
        _git(repository_root, "rev-parse", "--show-object-format")
        .stdout.decode("ascii")
        .strip()
    )
    tree_entries = bytearray()
    for entry in index_entries.split(b"\0"):
        if not entry:
            continue
        try:
            header, path = entry.split(b"\t", 1)
            mode, object_id, stage = header.split(b" ", 2)
        except ValueError as error:
            raise DiagnosticError("cannot interpret the production basis index") from error
        if stage != b"0":
            raise DiagnosticError(
                "production basis contains an unmerged index entry; refusing stale lineage"
            )
        if _worktree_blob_id(
            repository_root, path, mode, object_format
        ) != object_id:
            raise DiagnosticError(
                "production basis worktree bytes differ from the declared evidence "
                "commit; refusing stale lineage"
            )
        tree_entries.extend(mode + b" blob " + object_id + b"\t" + path + b"\0")
    if not tree_entries:
        raise DiagnosticError("working production basis contains no tracked paths")
    path_tree_sha256 = hashlib.sha256(tree_entries).hexdigest()
    if path_tree_sha256 != expected_path_tree_sha256:
        raise DiagnosticError(
            "production basis differs from the declared evidence commit; "
            "refusing stale lineage"
        )

    worktree_comparison = _git(
        repository_root,
        "diff",
        "--no-ext-diff",
        "--quiet",
        "--",
        *production_paths,
        check=False,
    )
    if worktree_comparison.returncode == 1:
        raise DiagnosticError(
            "production basis differs from the declared evidence commit; "
            "refusing stale lineage"
        )
    if worktree_comparison.returncode != 0:
        detail = worktree_comparison.stderr.decode("utf-8", errors="replace").strip()
        raise DiagnosticError(f"cannot compare production basis: {detail}")
    untracked = _git(
        repository_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *production_paths,
    ).stdout
    if untracked:
        raise DiagnosticError(
            "production basis contains untracked files; refusing stale lineage"
        )
    return {
        "declared_commit": declared_commit,
        "paths": list(production_paths),
        "path_tree_sha256": path_tree_sha256,
        "tracked_entry_count": tree_entries.count(b"\0"),
        "verified_against_worktree": True,
    }


def _evidence_tool_identity(
    *,
    startup_identity: Mapping[str, object] = _EVIDENCE_TOOL_IDENTITY_AT_STARTUP,
    path: Path = ROOT / TOOL_PATH,
) -> dict[str, object]:
    current_identity = _read_evidence_tool_identity(path)
    if current_identity != startup_identity:
        raise DiagnosticError(
            "evidence tool bytes changed after process startup; refusing stale lineage"
        )
    return dict(startup_identity)


def refuse_output_alias(output: Path, fixtures: Mapping[str, Path]) -> None:
    """Refuse an output path that names either immutable source object."""

    output_resolved = output.resolve(strict=False)
    for role, fixture in fixtures.items():
        fixture_resolved = fixture.resolve(strict=False)
        same_resolved_path = output_resolved == fixture_resolved
        same_existing_object = False
        if output.exists() or output.is_symlink():
            try:
                same_existing_object = output.samefile(fixture)
            except FileNotFoundError:
                same_existing_object = False
            except OSError as error:
                raise DiagnosticError(
                    f"cannot establish whether output aliases the {role} fixture"
                ) from error
        if same_resolved_path or same_existing_object:
            raise DiagnosticError(
                f"output aliases the {role} fixture; imported sources are immutable"
            )


def write_output_safely(
    output: Path,
    serialized: str,
    fixtures: Mapping[str, Path],
) -> None:
    """Publish output atomically without following a swapped destination alias."""

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as destination:
            destination.write(serialized)
            destination.flush()
            os.fsync(destination.fileno())

        # Revalidate immediately before publication.  os.replace then replaces
        # the destination directory entry itself: even a symlink or hard-link
        # swap after this check is not followed and cannot truncate a fixture.
        refuse_output_alias(output, fixtures)
        os.replace(temporary_path, output)
        temporary_path = None
    except OSError as error:
        raise DiagnosticError(f"cannot safely write diagnostic output: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


@dataclass(frozen=True)
class Calculation:
    plan: object
    forward: object
    backward: object
    floats: object
    result: Mapping[UUID, tuple[object, ...]]


@dataclass(frozen=True)
class Provenance:
    group_id: str
    causality: str
    paths: tuple[tuple[str, ...], ...]
    replay_driver_source_uid: str | None = None


@dataclass(frozen=True)
class VerifiedFixture:
    payload: bytes
    identity: dict[str, object]


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def verify_fixture(path: Path, expected: tuple[int, str], role: str) -> dict[str, object]:
    """Return the exact fixture identity or refuse a lookalike file."""

    return read_verified_fixture(path, expected, role).identity


def read_verified_fixture(
    path: Path, expected: tuple[int, str], role: str
) -> VerifiedFixture:
    """Retain the exact bytes whose fixture identity is accepted."""

    try:
        payload = path.read_bytes()
    except OSError as error:
        raise DiagnosticError(f"cannot read {role} fixture: {error}") from error
    actual = (len(payload), hashlib.sha256(payload).hexdigest())
    if actual != expected:
        raise DiagnosticError(
            f"{role} fixture identity mismatch: expected {expected[0]} bytes and "
            f"SHA-256 {expected[1]}, got {actual[0]} bytes and {actual[1]}"
        )
    return VerifiedFixture(
        payload=payload,
        identity={"bytes": actual[0], "sha256": actual[1]},
    )


def _source_uid(entity: object) -> str:
    refs = entity.external_refs
    if len(refs) != 1 or not refs[0].uid:
        raise DiagnosticError("entity lacks exactly one source identity")
    return str(refs[0].uid)


def _load(payload: bytes):
    with tempfile.TemporaryDirectory(prefix="sto-p1-g2-verified-") as directory:
        path = Path(directory) / "fixture.xml"
        path.write_bytes(payload)
        return migrate(import_mspdi(path))[0]


def _calculate(schedule: object) -> Calculation:
    start = schedule.project.start
    if start is None:
        raise DiagnosticError("controlled baseline has no project start")
    plan = build_plan(schedule, (start - timedelta(days=90), start + timedelta(days=365)))
    early = forward_pass(
        plan.network,
        snap_milestones=plan.snap_milestones,
        progress_policy=plan.progress_policy,
    )
    late = backward_pass(
        plan.network,
        early,
        snap_milestones=plan.snap_milestones,
        progress_policy=plan.progress_policy,
    )
    floats = float_analysis(
        plan.network,
        early,
        late,
        threshold=plan.critical_float_threshold,
    )
    early_by_uid = early.by_uid()
    late_by_uid = late.by_uid()
    float_by_uid = floats.by_uid()
    result = {
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
        for uid in plan.network.activity_by_uid()
    }
    return Calculation(plan, early, late, floats, result)


def _activities(schedule: object) -> dict[str, object]:
    return unique_rows((_source_uid(row), row) for row in schedule.activities)


def _observed(rows: Mapping[str, object]) -> dict[str, tuple[object, ...]]:
    return {
        source_uid: (
            row.source_observations.start,
            row.source_observations.finish,
            row.source_observations.early_start,
            row.source_observations.early_finish,
            row.source_observations.late_start,
            row.source_observations.late_finish,
            row.source_observations.total_float_seconds,
            row.source_observations.free_float_seconds,
            row.source_observations.critical,
        )
        for source_uid, row in rows.items()
    }


def _engine(schedule: object, result: Mapping[UUID, tuple[object, ...]]):
    return {
        _source_uid(row): result[row.uid]
        for row in schedule.activities
        if row.uid in result
    }


def _excluded(plan: object, schedule: object) -> dict[str, str]:
    source_by_uid = {row.uid: _source_uid(row) for row in schedule.activities}
    exclusions: dict[str, str] = {}
    for row in plan.excluded:
        if row.kind != "activity":
            continue
        source_uid = source_by_uid[row.uid]
        if source_uid in exclusions:
            raise DiagnosticError(f"duplicate activity exclusion for source UID {source_uid}")
        exclusions[source_uid] = row.code
    return exclusions


def _delta(field: str, source_value: object, sto_value: object) -> dict[str, object]:
    if isinstance(source_value, datetime) and isinstance(sto_value, datetime):
        return {
            "kind": "seconds",
            "sto_minus_source": int((sto_value - source_value).total_seconds()),
        }
    if field in {"total_float", "free_float"}:
        return {"kind": "seconds", "sto_minus_source": int(sto_value) - int(source_value)}
    if isinstance(source_value, bool) and isinstance(sto_value, bool):
        return {
            "kind": "boolean_transition",
            "direction": f"{str(source_value).lower()}_to_{str(sto_value).lower()}",
        }
    return {"kind": "changed"}


def _duration_class(value: object | None) -> str:
    if value is None:
        return "absent"
    seconds = int(value.seconds)
    magnitude = "negative" if seconds < 0 else "zero" if seconds == 0 else "positive"
    basis = "elapsed" if value.elapsed else "working"
    return f"{magnitude}_{basis}"


def _lag_classes(relationships: Sequence[object]) -> list[str]:
    return sorted(
        {
            "lead" if relationship.lag < 0 else "zero" if relationship.lag == 0 else "lag"
            for relationship in relationships
        }
    )


def _assumptions_by_uid(plan: object) -> dict[UUID, tuple[str, ...]]:
    rows: dict[UUID, set[str]] = defaultdict(set)
    for item in plan.assumed:
        if item.kind == "activity" and item.uid is not None:
            rows[item.uid].add(item.code)
    return {uid: tuple(sorted(codes)) for uid, codes in rows.items()}


def _raw_relationships(schedule: object):
    incoming: dict[UUID, list[object]] = defaultdict(list)
    outgoing: dict[UUID, list[object]] = defaultdict(list)
    for relationship in schedule.relationships:
        incoming[relationship.successor_uid].append(relationship)
        outgoing[relationship.predecessor_uid].append(relationship)
    return incoming, outgoing


def _local_group(
    uid: UUID,
    *,
    direction: str,
    assumptions: Mapping[UUID, Sequence[str]],
    raw_outgoing: Mapping[UUID, Sequence[object]],
    activities: Mapping[UUID, object],
) -> str:
    codes = set(assumptions.get(uid, ()))
    if "ACTIVITY_RESOURCE_CALENDARS_UNITED" in codes:
        return MULTI_RESOURCE
    if "ACTIVITY_SUCCESSOR_OF_INACTIVE" in codes:
        return INACTIVE_BOUNDARY
    if direction == "late" and any(
        not activities[row.successor_uid].active for row in raw_outgoing.get(uid, ())
    ):
        return INACTIVE_BOUNDARY
    return UNKNOWN


def _merge_paths(provenances: Iterable[Provenance]) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted({path for item in provenances for path in item.paths}))


def _coordinate_provenance(schedule: object, calculation: Calculation):
    plan = calculation.plan
    early = calculation.forward
    late = calculation.backward
    activities = {row.uid: row for row in schedule.activities}
    source_by_uid = {uid: _source_uid(row) for uid, row in activities.items()}
    planned = plan.network.activity_by_uid()
    incoming = plan.network.predecessors()
    outgoing = plan.network.successors()
    relationships = {row.uid: row for row in plan.network.relationships}
    calendars = {uid: row.calendar for uid, row in planned.items()}
    assumptions = _assumptions_by_uid(plan)
    _, raw_outgoing = _raw_relationships(schedule)
    early_by_uid = early.by_uid()
    late_by_uid = late.by_uid()
    source_early = {
        uid: ActivityTimes(
            uid,
            plan.to_seconds(row.source_observations.early_start),
            plan.to_seconds(row.source_observations.early_finish),
            state=ProgressState.NOT_STARTED,
        )
        for uid, row in activities.items()
        if uid in early_by_uid
    }
    source_late = {
        uid: ActivityLateTimes(
            uid,
            plan.to_seconds(row.source_observations.late_start),
            plan.to_seconds(row.source_observations.late_finish),
        )
        for uid, row in activities.items()
        if uid in late_by_uid
    }
    provenance: dict[tuple[UUID, str], Provenance | None] = {}
    replay_drivers: dict[tuple[UUID, str], str | None] = {}

    for uid in early.order:
        actual = early_by_uid[uid]
        expected = source_early[uid]
        activity = planned[uid]
        incident = incoming[uid]
        base = None if incident else plan.network.project_start
        unbounded_floor = base if base is not None else plan.network.project_start
        start_bound, finish_bound, start_driver, finish_driver = forward_bounds(
            activity,
            incident,
            source_early,
            base,
            unbounded_floor,
        )
        predicted = forward_place(
            activity,
            activity.remaining,
            start_bound,
            finish_bound,
            plan.network.horizon,
            plan.snap_milestones,
            None,
            None,
        )
        floor = base if base is not None else (activity.calendar.first or 0)
        replay_driver_uid = forward_driver(
            activity,
            activity.remaining,
            start_bound,
            finish_bound,
            start_driver,
            finish_driver,
            floor,
            plan.network.horizon,
            plan.snap_milestones,
        )
        replay_edge = relationships.get(replay_driver_uid)
        replay_source = (
            None
            if replay_edge is None
            else source_by_uid[replay_edge.predecessor_uid]
        )
        for field, actual_value, expected_value, predicted_value in (
            ("early_start", actual.early_start, expected.early_start, predicted[0]),
            ("early_finish", actual.early_finish, expected.early_finish, predicted[1]),
        ):
            replay_drivers[(uid, field)] = replay_source
            if actual_value == expected_value:
                provenance[(uid, field)] = None
                continue
            if predicted_value != expected_value:
                group_id = _local_group(
                    uid,
                    direction="forward",
                    assumptions=assumptions,
                    raw_outgoing=raw_outgoing,
                    activities=activities,
                )
                provenance[(uid, field)] = Provenance(
                    group_id,
                    "ROOT",
                    ((source_by_uid[uid],),),
                    replay_source,
                )
                continue
            if replay_edge is None:
                provenance[(uid, field)] = Provenance(
                    UNKNOWN, "ROOT", ((source_by_uid[uid],),), None
                )
                continue
            dependency_field = (
                "early_finish" if replay_edge.anchors_predecessor_finish else "early_start"
            )
            inherited = provenance.get((replay_edge.predecessor_uid, dependency_field))
            if inherited is None:
                provenance[(uid, field)] = Provenance(
                    UNKNOWN, "ROOT", ((source_by_uid[uid],),), replay_source
                )
                continue
            provenance[(uid, field)] = Provenance(
                inherited.group_id,
                "PROPAGATED",
                tuple(path + (source_by_uid[uid],) for path in inherited.paths),
                replay_source,
            )

    released = frozenset(late.overridden_relationships)
    for uid in reversed(early.order):
        actual = late_by_uid[uid]
        expected = source_late[uid]
        activity = planned[uid]
        start_bound, finish_bound, start_driver, finish_driver = backward_bounds(
            activity,
            outgoing[uid],
            source_late,
            early_by_uid,
            late.project_late_finish,
            calendars,
            released,
            plan.network.horizon,
        )
        predicted = backward_place(
            activity,
            activity.remaining,
            start_bound,
            finish_bound,
            plan.snap_milestones,
            None,
            None,
        )
        replay_driver_uid = backward_driver(
            activity,
            activity.remaining,
            start_bound,
            finish_bound,
            start_driver,
            finish_driver,
            late.project_late_finish,
        )
        replay_edge = relationships.get(replay_driver_uid)
        replay_source = (
            None if replay_edge is None else source_by_uid[replay_edge.successor_uid]
        )
        for field, actual_value, expected_value, predicted_value in (
            ("late_start", actual.late_start, expected.late_start, predicted[0]),
            ("late_finish", actual.late_finish, expected.late_finish, predicted[1]),
        ):
            replay_drivers[(uid, field)] = replay_source
            if actual_value == expected_value:
                provenance[(uid, field)] = None
                continue
            if predicted_value != expected_value:
                group_id = _local_group(
                    uid,
                    direction="late",
                    assumptions=assumptions,
                    raw_outgoing=raw_outgoing,
                    activities=activities,
                )
                provenance[(uid, field)] = Provenance(
                    group_id,
                    "ROOT",
                    ((source_by_uid[uid],),),
                    replay_source,
                )
                continue
            if replay_edge is None:
                provenance[(uid, field)] = Provenance(
                    UNKNOWN, "ROOT", ((source_by_uid[uid],),), None
                )
                continue
            dependency_field = (
                "late_start" if replay_edge.bounds_successor_start else "late_finish"
            )
            inherited = provenance.get((replay_edge.successor_uid, dependency_field))
            if inherited is None:
                provenance[(uid, field)] = Provenance(
                    UNKNOWN, "ROOT", ((source_by_uid[uid],),), replay_source
                )
                continue
            provenance[(uid, field)] = Provenance(
                inherited.group_id,
                "PROPAGATED",
                tuple(path + (source_by_uid[uid],) for path in inherited.paths),
                replay_source,
            )

    return provenance, replay_drivers, source_early, source_late


def _source_float_replay(
    calculation: Calculation,
    source_early: Mapping[UUID, ActivityTimes],
    source_late: Mapping[UUID, ActivityLateTimes],
):
    early = calculation.forward
    late = calculation.backward
    replaced_early = tuple(
        replace(
            row,
            early_start=source_early[row.uid].early_start,
            early_finish=source_early[row.uid].early_finish,
        )
        for row in early.times
    )
    replaced_late = tuple(
        replace(
            row,
            late_start=source_late[row.uid].late_start,
            late_finish=source_late[row.uid].late_finish,
            remaining_start=None,
        )
        for row in late.times
    )
    source_forward = replace(
        early,
        times=replaced_early,
        project_start=min(row.early_start for row in replaced_early),
        project_finish=max(row.early_finish for row in replaced_early),
    )
    source_backward = replace(
        late,
        times=replaced_late,
        project_late_finish=max(row.late_finish for row in replaced_late),
    )
    return float_analysis(
        calculation.plan.network,
        source_forward,
        source_backward,
        threshold=calculation.plan.critical_float_threshold,
    ).by_uid()


def _combine_coordinate_provenance(items: Iterable[Provenance | None]) -> Provenance:
    present = tuple(item for item in items if item is not None)
    groups = {item.group_id for item in present}
    if groups == {MULTI_RESOURCE, INACTIVE_BOUNDARY}:
        return Provenance(COMPOUND_FLOAT, "COMPOUND", _merge_paths(present))
    if len(groups) == 1:
        return Provenance(next(iter(groups)), "PROPAGATED", _merge_paths(present))
    return Provenance(UNKNOWN, "ROOT", _merge_paths(present))


def _movement_finish_limits(calculation: Calculation) -> dict[UUID, int]:
    limits: dict[UUID, int] = {}
    horizon = calculation.plan.network.horizon
    early = calculation.forward.by_uid()
    exactly_pinned = frozenset(
        uid
        for uid, activity in calculation.plan.network.activity_by_uid().items()
        if early[uid].state is ProgressState.NOT_STARTED
        and activity.constraint_type in (ConstraintType.MSO, ConstraintType.MFO)
    )
    for uid, activity in calculation.plan.network.activity_by_uid().items():
        if activity.remaining == 0:
            limit = horizon
            if (
                calculation.plan.snap_milestones
                and early[uid].state is not ProgressState.COMPLETE
                and uid not in exactly_pinned
            ):
                snapped_limit = prev_working_start(activity.calendar, horizon)
                if snapped_limit is None:
                    raise DiagnosticError(
                        f"no snapped movement limit for source UID {uid}"
                    )
                limit = snapped_limit
            limits[uid] = limit
            continue
        floor = activity.calendar.first
        span = (
            None
            if floor is None
            else latest_span(
                activity.calendar,
                horizon,
                horizon,
                activity.remaining,
                floor,
            )
        )
        if span is None:
            raise DiagnosticError(f"no movement limit for source UID {uid}")
        limits[uid] = span[1]
    return limits


def _free_float_candidates(
    uid: UUID,
    times: Mapping[UUID, ActivityTimes],
    calculation: Calculation,
    movement_finish: Mapping[UUID, int],
) -> tuple[tuple[object | None, int], ...]:
    plan = calculation.plan
    activities = plan.network.activity_by_uid()
    outgoing = plan.network.successors()[uid]
    activity = activities[uid]
    row = times[uid]
    if not outgoing:
        return (
            (
                None,
                signed_working(
                    activity.float_calendar,
                    row.early_finish,
                    calculation.backward.project_late_finish,
                ),
            ),
        )
    candidates: list[tuple[object, int]] = []
    for relationship in outgoing:
        successor = times[relationship.successor_uid]
        available = (
            successor.early_start
            if relationship.bounds_successor_start
            else successor.early_finish
        )
        lag_calendar = lag_calendar_for(
            relationship, activities[relationship.successor_uid].calendar
        )
        permitted = unshift_lag(
            lag_calendar,
            available,
            relationship.lag,
            ceiling=movement_finish[uid],
        )
        if permitted is None:
            raise DiagnosticError("free-float replay could not invert a production edge")
        anchor = (
            row.early_finish
            if relationship.anchors_predecessor_finish
            else row.early_start
        )
        candidates.append(
            (
                relationship,
                signed_working(activity.float_calendar, anchor, permitted),
            )
        )
    return tuple(candidates)


def _float_provenance(
    schedule: object,
    calculation: Calculation,
    coordinate: Mapping[tuple[UUID, str], Provenance | None],
    source_early: Mapping[UUID, ActivityTimes],
    source_late: Mapping[UUID, ActivityLateTimes],
):
    plan = calculation.plan
    activities = {row.uid: row for row in schedule.activities}
    assumptions = _assumptions_by_uid(plan)
    _, raw_outgoing = _raw_relationships(schedule)
    actual = calculation.floats.by_uid()
    replay = _source_float_replay(calculation, source_early, source_late)
    actual_early = calculation.forward.by_uid()
    movement_finish = _movement_finish_limits(calculation)
    provenance: dict[tuple[UUID, str], Provenance | None] = {}

    def direct(uid: UUID) -> Provenance:
        codes = set(assumptions.get(uid, ()))
        if "ACTIVITY_DURATION_ELAPSED" in codes:
            group_id = ELAPSED_FLOAT
        elif any(
            not activities[row.successor_uid].active for row in raw_outgoing.get(uid, ())
        ):
            group_id = INACTIVE_BOUNDARY
        else:
            group_id = UNKNOWN
        source_uid = _source_uid(activities[uid])
        return Provenance(group_id, "ROOT", ((source_uid,),))

    for uid in calculation.forward.order:
        observed = activities[uid].source_observations
        actual_row = actual[uid]
        replay_row = replay[uid]

        if actual_row.total_float == observed.total_float_seconds:
            provenance[(uid, "total_float")] = None
        elif replay_row.total_float != observed.total_float_seconds:
            provenance[(uid, "total_float")] = direct(uid)
        else:
            actual_components = (actual_row.start_float, actual_row.finish_float)
            replay_components = (replay_row.start_float, replay_row.finish_float)
            relevant = {
                index
                for index, value in enumerate(actual_components)
                if value == min(actual_components)
            } | {
                index
                for index, value in enumerate(replay_components)
                if value == min(replay_components)
            }
            dependencies: list[Provenance | None] = []
            for index in relevant:
                if actual_components[index] == replay_components[index]:
                    continue
                if index == 0:
                    dependencies.extend(
                        (coordinate[(uid, "early_start")], coordinate[(uid, "late_start")])
                    )
                else:
                    dependencies.extend(
                        (coordinate[(uid, "early_finish")], coordinate[(uid, "late_finish")])
                    )
            provenance[(uid, "total_float")] = _combine_coordinate_provenance(
                dependencies
            )

        if actual_row.free_float == observed.free_float_seconds:
            provenance[(uid, "free_float")] = None
        elif replay_row.free_float != observed.free_float_seconds:
            provenance[(uid, "free_float")] = direct(uid)
        else:
            actual_candidates = _free_float_candidates(
                uid, actual_early, calculation, movement_finish
            )
            replay_candidates = _free_float_candidates(
                uid, source_early, calculation, movement_finish
            )
            if min(value for _, value in actual_candidates) != actual_row.free_float:
                raise DiagnosticError("actual free-float driver replay diverged from production")
            if min(value for _, value in replay_candidates) != replay_row.free_float:
                raise DiagnosticError("source free-float driver replay diverged from production")
            selected = [
                relationship
                for relationship, value in actual_candidates
                if value == actual_row.free_float
            ] + [
                relationship
                for relationship, value in replay_candidates
                if value == replay_row.free_float
            ]
            dependencies: list[Provenance | None] = []
            own_field = "early_finish"
            if any(
                relationship is not None
                and not relationship.anchors_predecessor_finish
                for relationship in selected
            ):
                own_field = "early_start"
            dependencies.append(coordinate[(uid, own_field)])
            for relationship in selected:
                if relationship is None:
                    continue
                successor_field = (
                    "early_start"
                    if relationship.bounds_successor_start
                    else "early_finish"
                )
                dependencies.append(
                    coordinate[(relationship.successor_uid, successor_field)]
                )
            provenance[(uid, "free_float")] = _combine_coordinate_provenance(
                dependencies
            )

        if actual_row.critical == observed.critical:
            provenance[(uid, "critical")] = None
        else:
            total = provenance[(uid, "total_float")]
            provenance[(uid, "critical")] = (
                Provenance(UNKNOWN, "ROOT", ((_source_uid(activities[uid]),),))
                if total is None
                else Provenance(total.group_id, "DERIVED", total.paths)
            )
    return provenance


def _driver_source_uids(schedule: object, calculation: Calculation):
    source_by_uid = {row.uid: _source_uid(row) for row in schedule.activities}
    relationships = {row.uid: row for row in calculation.plan.network.relationships}
    forward: dict[UUID, str | None] = {}
    late: dict[UUID, str | None] = {}
    for row in calculation.forward.times:
        edge = relationships.get(row.driving_relationship_uid)
        forward[row.uid] = None if edge is None else source_by_uid[edge.predecessor_uid]
    for row in calculation.backward.times:
        edge = relationships.get(row.driving_relationship_uid)
        late[row.uid] = None if edge is None else source_by_uid[edge.successor_uid]
    return forward, late


def _components(
    mismatch_uids: set[UUID],
    schedule: object,
    calculation: Calculation,
    leaf_ids: Mapping[str, str],
) -> tuple[list[dict[str, object]], dict[UUID, str]]:
    relationships = {row.uid: row for row in calculation.plan.network.relationships}
    adjacency = {uid: set() for uid in mismatch_uids}
    for rows in (calculation.forward.times, calculation.backward.times):
        for row in rows:
            if row.uid not in mismatch_uids or row.driving_relationship_uid is None:
                continue
            edge = relationships[row.driving_relationship_uid]
            other = (
                edge.predecessor_uid
                if row.uid == edge.successor_uid
                else edge.successor_uid
            )
            if other in mismatch_uids:
                adjacency[row.uid].add(other)
                adjacency[other].add(row.uid)
    source_by_uid = {row.uid: _source_uid(row) for row in schedule.activities}
    pending = set(mismatch_uids)
    found: list[set[UUID]] = []
    while pending:
        start = min(pending, key=lambda uid: int(source_by_uid[uid]))
        component = {start}
        frontier = [start]
        pending.remove(start)
        while frontier:
            current = frontier.pop()
            for adjacent in adjacency[current]:
                if adjacent in pending:
                    pending.remove(adjacent)
                    component.add(adjacent)
                    frontier.append(adjacent)
        found.append(component)
    found.sort(
        key=lambda group: (-len(group), min(int(source_by_uid[uid]) for uid in group))
    )
    rows: list[dict[str, object]] = []
    by_uid: dict[UUID, str] = {}
    for index, group in enumerate(found, 1):
        component_id = f"G2-C{index:02d}"
        for uid in group:
            by_uid[uid] = component_id
        rows.append(
            {
                "component_id": component_id,
                "leaf_count": len(group),
                "leaf_ids": sorted(leaf_ids[source_by_uid[uid]] for uid in group),
            }
        )
    return rows, by_uid


def _activity_context(schedule: object, calculation: Calculation, uid: UUID) -> dict[str, object]:
    activity = next(row for row in schedule.activities if row.uid == uid)
    planned = calculation.plan.network.activity_by_uid()[uid]
    assumptions = _assumptions_by_uid(calculation.plan).get(uid, ())
    assignments = [row for row in schedule.assignments if row.activity_uid == uid]
    resources = {row.uid: row for row in schedule.resources}
    resource_calendars = {
        resources[row.resource_uid].calendar_uid
        for row in assignments
        if row.resource_uid in resources and resources[row.resource_uid].calendar_uid is not None
    }
    incoming = calculation.plan.network.predecessors()[uid]
    outgoing = calculation.plan.network.successors()[uid]
    if "ACTIVITY_DURATION_ELAPSED" in assumptions:
        calendar_class = "elapsed_continuous"
    elif "ACTIVITY_RESOURCE_CALENDARS_UNITED" in assumptions:
        calendar_class = "resource_calendar_union"
    elif resource_calendars:
        calendar_class = "single_resource_calendar"
    elif activity.calendar_uid is not None:
        calendar_class = "task_calendar"
    else:
        calendar_class = "project_calendar"
    return {
        "disposition": "ASSUMED_LABELLED" if assumptions else "SUPPORTED_CALCULATED",
        "progress_state": calculation.forward.by_uid()[uid].state.value,
        "activity_kind": activity.kind.value,
        "active": activity.active,
        "manual": activity.manual,
        "planned_duration_class": _duration_class(activity.planned_duration),
        "remaining_duration_class": _duration_class(activity.remaining_duration),
        "calendar_class": calendar_class,
        "resource_calendar_count": len(resource_calendars),
        "assignment_count": len(assignments),
        "constraint_type": planned.constraint_type.value,
        "incoming_relationship_types": sorted({row.type.value for row in incoming}),
        "outgoing_relationship_types": sorted({row.type.value for row in outgoing}),
        "incoming_lag_classes": _lag_classes(incoming),
        "outgoing_lag_classes": _lag_classes(outgoing),
        "assumption_codes": list(assumptions),
    }


def _multi_resource_envelope_evidence(schedule: object, root_uids: set[UUID]):
    assignments: dict[UUID, list[object]] = defaultdict(list)
    for row in schedule.assignments:
        assignments[row.activity_uid].append(row)
    activities = {row.uid: row for row in schedule.activities}
    proved: list[str] = []
    for uid in root_uids:
        row = activities[uid]
        spans = [
            item
            for item in assignments[uid]
            if item.start is not None and item.finish is not None
        ]
        if not spans:
            raise DiagnosticError("multi-resource root lacks stored assignment spans")
        envelope = (min(item.start for item in spans), max(item.finish for item in spans))
        observed = row.source_observations
        if envelope != (observed.start, observed.finish):
            raise DiagnosticError(
                f"source UID {_source_uid(row)} does not equal its assignment envelope"
            )
        proved.append(_source_uid(row))
    return sorted(proved, key=int)


def _elapsed_float_evidence(schedule: object, root_uids: set[UUID], plan: object):
    activities = {row.uid: row for row in schedule.activities}
    outgoing = plan.network.successors()
    total_proved: list[str] = []
    free_proved: list[str] = []
    for uid in root_uids:
        row = activities[uid]
        observed = row.source_observations
        start_gap = plan.to_seconds(observed.late_start) - plan.to_seconds(observed.early_start)
        finish_gap = plan.to_seconds(observed.late_finish) - plan.to_seconds(observed.early_finish)
        if observed.total_float_seconds not in {start_gap, finish_gap}:
            raise DiagnosticError(
                f"source UID {_source_uid(row)} elapsed float does not match a coordinate gap"
            )
        total_proved.append(_source_uid(row))
        free_candidates: list[int] = []
        for relationship in outgoing[uid]:
            if relationship.lag != 0:
                raise DiagnosticError(
                    "elapsed-float evidence requires an explicit lag replay"
                )
            successor = activities[relationship.successor_uid].source_observations
            anchor = (
                observed.early_finish
                if relationship.anchors_predecessor_finish
                else observed.early_start
            )
            available = (
                successor.early_start
                if relationship.bounds_successor_start
                else successor.early_finish
            )
            free_candidates.append(int((available - anchor).total_seconds()))
        if not free_candidates:
            free_candidates.append(
                plan.to_seconds(schedule.project.finish)
                - plan.to_seconds(observed.early_finish)
            )
        if observed.free_float_seconds != min(free_candidates):
            raise DiagnosticError(
                f"source UID {_source_uid(row)} elapsed free float is not its coordinate gap"
            )
        free_proved.append(_source_uid(row))
    return {
        "total_float": sorted(total_proved, key=int),
        "free_float": sorted(free_proved, key=int),
    }


def _inactive_boundary_evidence(schedule: object, root_uids: set[UUID]):
    activities = {row.uid: row for row in schedule.activities}
    incoming, outgoing = _raw_relationships(schedule)
    active_successors: list[str] = []
    active_predecessors: list[str] = []
    for uid in root_uids:
        predecessor_boundary = any(
            not activities[row.predecessor_uid].active for row in incoming.get(uid, ())
        )
        successor_boundary = any(
            not activities[row.successor_uid].active for row in outgoing.get(uid, ())
        )
        if not predecessor_boundary and not successor_boundary:
            raise DiagnosticError(
                f"source UID {_source_uid(activities[uid])} is not adjacent to an inactive row"
            )
        if predecessor_boundary:
            active_successors.append(_source_uid(activities[uid]))
        if successor_boundary:
            active_predecessors.append(_source_uid(activities[uid]))
    return {
        "active_successors_of_inactive_source_uids": sorted(
            active_successors, key=int
        ),
        "active_predecessors_of_inactive_source_uids": sorted(
            active_predecessors, key=int
        ),
    }


def build_record(baseline_path: Path, repeat_path: Path) -> dict[str, object]:
    """Build the deterministic, sanitized 422-slot diagnosis."""

    production_basis = verify_production_basis()
    baseline_fixture = read_verified_fixture(
        baseline_path, BASELINE_IDENTITY, "BOILER baseline"
    )
    repeat_fixture = read_verified_fixture(
        repeat_path, REPEAT_IDENTITY, "UID 227 clean repeat"
    )
    fixtures = {
        "boiler_baseline": baseline_fixture.identity,
        "uid227_clean_repeat": repeat_fixture.identity,
    }
    baseline = _load(baseline_fixture.payload)
    native = _load(repeat_fixture.payload)
    baseline_rows = _activities(baseline)
    native_rows = _activities(native)
    if set(baseline_rows) != set(native_rows):
        raise DiagnosticError("controlled repeat changed the activity identity cohort")
    leaf_ids = {
        source_uid: f"L{index:04d}"
        for index, source_uid in enumerate(sorted(baseline_rows, key=int), 1)
    }
    if native.snapshots[0].application_version != TARGET_BUILD:
        raise DiagnosticError("controlled repeat does not carry the recorded Project build")

    selected = baseline_rows[TARGET_SOURCE_UID]
    controlled_selected = replace(
        selected,
        actual_start=TARGET_ACTUAL_START,
        remaining_duration=replace(
            selected.remaining_duration,
            seconds=TARGET_REMAINING_SECONDS,
        ),
    )
    controlled = replace(
        baseline,
        activities=tuple(
            controlled_selected if row.uid == selected.uid else row
            for row in baseline.activities
        ),
    )
    baseline_calc = _calculate(baseline)
    controlled_calc = _calculate(controlled)
    native_calc = _calculate(native)
    summary = classify_controlled_transition(
        _observed(baseline_rows),
        _observed(native_rows),
        _engine(baseline, baseline_calc.result),
        _engine(baseline, controlled_calc.result),
        _engine(native, native_calc.result),
        _excluded(baseline_calc.plan, baseline),
    )
    if dict(summary.classifications) != EXPECTED_CLASSIFICATIONS:
        raise DiagnosticError(
            "authoritative comparison matrix did not reproduce: "
            f"{dict(summary.classifications)}"
        )
    if summary.unexpected_transition_count != 0:
        raise DiagnosticError("clean controlled transition has unexpected differences")
    by_field = Counter(field for _, field in summary.baseline_mismatches)
    if dict(by_field) != EXPECTED_BY_FIELD:
        raise DiagnosticError(f"baseline mismatch field distribution moved: {by_field}")
    affected_source_uids = {source_uid for source_uid, _ in summary.baseline_mismatches}
    if len(affected_source_uids) != 105:
        raise DiagnosticError("authoritative mismatch leaf count did not reproduce")

    activities = {row.uid: row for row in baseline.activities}
    uid_by_source = {_source_uid(row): row.uid for row in baseline.activities}
    mismatch_uids = {uid_by_source[source_uid] for source_uid in affected_source_uids}
    coordinate, replay_drivers, source_early, source_late = _coordinate_provenance(
        baseline, baseline_calc
    )
    float_provenance = _float_provenance(
        baseline,
        baseline_calc,
        coordinate,
        source_early,
        source_late,
    )
    provenance = dict(coordinate)
    provenance.update(float_provenance)
    forward_drivers, late_drivers = _driver_source_uids(baseline, baseline_calc)
    components, component_by_uid = _components(
        mismatch_uids, baseline, baseline_calc, leaf_ids
    )

    observed_rows = _observed(baseline_rows)
    engine_rows = _engine(baseline, baseline_calc.result)
    inventory: list[dict[str, object]] = []
    slots_by_group: dict[str, list[dict[str, object]]] = defaultdict(list)
    for source_uid, field in summary.baseline_mismatches:
        uid = uid_by_source[source_uid]
        if field == "start":
            basis_field = "early_start"
        elif field == "finish":
            basis_field = "early_finish"
        else:
            basis_field = field
        cause = provenance.get((uid, basis_field))
        if cause is None:
            cause = Provenance(UNKNOWN, "ROOT", ((source_uid,),))
        source_value = observed_rows[source_uid][RESULT_FIELDS.index(field)]
        sto_value = engine_rows[source_uid][RESULT_FIELDS.index(field)]
        record = {
            "_source_uid": source_uid,
            "leaf_id": leaf_ids[source_uid],
            "field": field,
            "delta": _delta(field, source_value, sto_value),
            "diagnostic_group": cause.group_id,
            "causal_confidence": GROUP_DEFINITIONS[cause.group_id]["status"],
            "dependency_role": DEPENDENCY_ROLES[cause.causality],
            "dependency_paths": [
                [leaf_ids[path_source_uid] for path_source_uid in path]
                for path in cause.paths
            ],
            "component_id": component_by_uid[uid],
            "forward_driver_predecessor_leaf_id": (
                None
                if forward_drivers[uid] is None
                else leaf_ids[forward_drivers[uid]]
            ),
            "late_driver_successor_leaf_id": (
                None if late_drivers[uid] is None else leaf_ids[late_drivers[uid]]
            ),
            "source_replay_driver_leaf_id": (
                None
                if replay_drivers.get((uid, basis_field)) is None
                else leaf_ids[replay_drivers[(uid, basis_field)]]
            ),
            "mismatched_engine_driver": (
                forward_drivers[uid] in affected_source_uids
                if field in {"start", "finish", "early_start", "early_finish"}
                else late_drivers[uid] in affected_source_uids
                if field in {"late_start", "late_finish"}
                else None
            ),
        }
        inventory.append(record)
        slots_by_group[cause.group_id].append(record)

    unique_slots = {(row["_source_uid"], row["field"]) for row in inventory}
    if len(inventory) != 422 or len(unique_slots) != 422:
        raise DiagnosticError("mismatch inventory is not an exact 422-slot partition")

    activity_context = {
        leaf_ids[source_uid]: _activity_context(
            baseline, baseline_calc, uid_by_source[source_uid]
        )
        for source_uid in sorted(affected_source_uids, key=int)
    }
    component_slots = Counter(row["component_id"] for row in inventory)
    component_fields: dict[str, Counter[str]] = defaultdict(Counter)
    for row in inventory:
        component_fields[row["component_id"]][row["field"]] += 1
    for row in components:
        row["field_slot_count"] = component_slots[row["component_id"]]
        row["field_distribution"] = dict(
            sorted(component_fields[row["component_id"]].items())
        )

    group_rows: list[dict[str, object]] = []
    root_uids_by_group: dict[str, set[UUID]] = defaultdict(set)
    for group_id, slots in slots_by_group.items():
        for slot in slots:
            if slot["dependency_role"] in {"FIRST_DIVERGENCE", "COMPOUND"}:
                root_uids_by_group[group_id].add(uid_by_source[slot["_source_uid"]])
    for group_id in (MULTI_RESOURCE, INACTIVE_BOUNDARY, ELAPSED_FLOAT, COMPOUND_FLOAT, UNKNOWN):
        slots = slots_by_group.get(group_id, [])
        if not slots and group_id == UNKNOWN:
            continue
        roots = {
            slot["_source_uid"]
            for slot in slots
            if slot["dependency_role"] in {"FIRST_DIVERGENCE", "COMPOUND"}
        }
        affected = {slot["_source_uid"] for slot in slots}
        propagated_only = affected - roots
        definition = GROUP_DEFINITIONS[group_id]
        row = {
            "group_id": group_id,
            **definition,
            "affected_leaf_count": len(affected),
            "root_leaf_count": len(roots),
            "propagated_leaf_count": len(propagated_only),
            "field_slot_count": len(slots),
            "field_distribution": dict(
                sorted(Counter(slot["field"] for slot in slots).items())
            ),
            "root_leaf_ids": sorted(leaf_ids[source_uid] for source_uid in roots),
        }
        if group_id == MULTI_RESOURCE:
            envelope_source_uids = _multi_resource_envelope_evidence(
                baseline, root_uids_by_group[MULTI_RESOURCE]
            )
            row["evidence"] = {
                "root_task_span_equals_assignment_envelope_leaf_ids": sorted(
                    leaf_ids[source_uid] for source_uid in envelope_source_uids
                ),
                "source_dependency_replay": "all propagated date slots close",
            }
        elif group_id == INACTIVE_BOUNDARY:
            boundary_evidence = _inactive_boundary_evidence(
                baseline, root_uids_by_group[INACTIVE_BOUNDARY]
            )
            row["evidence"] = {
                "inactive_endpoint_adjacency": {
                    "active_successors_of_inactive_leaf_ids": sorted(
                        leaf_ids[source_uid]
                        for source_uid in boundary_evidence[
                            "active_successors_of_inactive_source_uids"
                        ]
                    ),
                    "active_predecessors_of_inactive_leaf_ids": sorted(
                        leaf_ids[source_uid]
                        for source_uid in boundary_evidence[
                            "active_predecessors_of_inactive_source_uids"
                        ]
                    ),
                },
                "source_dependency_replay": "all propagated date slots close",
                "source_date_float_replay": (
                    "predecessors of excluded inactive endpoints retain two direct "
                    "Free Slack residuals"
                ),
            }
        elif group_id == ELAPSED_FLOAT:
            elapsed_evidence = _elapsed_float_evidence(
                baseline, root_uids_by_group[ELAPSED_FLOAT], baseline_calc.plan
            )
            row["evidence"] = {
                "source_float_equals_elapsed_coordinate_gap_leaf_ids": {
                    field: sorted(leaf_ids[source_uid] for source_uid in source_uids)
                    for field, source_uids in elapsed_evidence.items()
                },
                "source_date_replay_residual_slots": len(slots),
            }
        elif group_id == COMPOUND_FLOAT:
            row["evidence"] = {
                "coordinate_root_groups": [MULTI_RESOURCE, INACTIVE_BOUNDARY]
            }
        group_rows.append(row)

    group_total = sum(row["field_slot_count"] for row in group_rows)
    if group_total != 422:
        raise DiagnosticError(f"root-cause groups reconcile to {group_total}, not 422")
    status_slots = Counter()
    for row in group_rows:
        status_slots[row["status"]] += row["field_slot_count"]

    signatures: Counter[tuple[str, ...]] = Counter()
    fields_by_source: dict[str, list[str]] = defaultdict(list)
    for source_uid, field in summary.baseline_mismatches:
        fields_by_source[source_uid].append(field)
    for fields in fields_by_source.values():
        signatures[tuple(field for field in RESULT_FIELDS if field in fields)] += 1

    scheduled_uids = set(baseline_calc.plan.network.activity_by_uid())
    activity_exclusions = [
        row for row in baseline_calc.plan.excluded if row.kind == "activity"
    ]
    excluded_uids = {row.uid for row in activity_exclusions}
    if scheduled_uids & excluded_uids or scheduled_uids | excluded_uids != set(activities):
        raise DiagnosticError("baseline activities do not form a scheduled/excluded partition")
    assumed_activity_uids = {
        row.uid
        for row in baseline_calc.plan.assumed
        if row.kind == "activity" and row.uid is not None
    }

    # There is no responsible production patch yet.  The inactive boundary is
    # the largest class, but its simplest previously tested rule was falsified.
    # Record the smallest experiment instead of pretending a fix is known.
    next_action = {
        "decision": "NO_PRODUCTION_FIX_JUSTIFIED_YET",
        "diagnostic_group": INACTIVE_BOUNDARY,
        "causal_confidence": GROUP_DEFINITIONS[INACTIVE_BOUNDARY]["status"],
        "name": GROUP_DEFINITIONS[INACTIVE_BOUNDARY]["name"],
        "owned_mismatch_slots": len(slots_by_group[INACTIVE_BOUNDARY]),
        "owned_leaves": len(
            {slot["_source_uid"] for slot in slots_by_group[INACTIVE_BOUNDARY]}
        ),
        "expected_net_mismatch_reduction": None,
        "production_area_if_proven": [
            "src/sto/core/engine/plan.py",
            "src/sto/core/engine/forward.py",
            "src/sto/core/engine/backward.py",
            "src/sto/core/engine/criticality.py",
        ],
        "required_experiment": (
            "A minimal native Project matrix for active-to-inactive-to-active FS logic, "
            "covering both forward placement and predecessor late/free-float influence."
        ),
        "required_regression": (
            "The isolated matrix must establish one rule that predicts both sides of the "
            "inactive row; do not reuse the rejected zero-duration pass-through guess."
        ),
        "required_post_fix_evidence": (
            "Rerun the exact 422-slot inventory, the three real-file forward/backward "
            "cohorts, conformance, and the complete repository suite."
        ),
    }
    public_inventory = [
        {key: value for key, value in slot.items() if key != "_source_uid"}
        for slot in inventory
    ]

    return {
        "schema": SCHEMA,
        "evidence_date": EVIDENCE_DATE,
        "repository_base": REPOSITORY_BASE,
        "lineage": {
            "production_basis": production_basis,
            "evidence_tool": _evidence_tool_identity(),
        },
        "classification_contract": {
            "diagnostic_group": (
                "A deterministic mechanical mismatch family; membership alone does not "
                "prove its causal semantic."
            ),
            "root_leaf": (
                "A first-divergence or compound row in the replay, not automatically a "
                "proven causal root."
            ),
            "causal_confidence": (
                "PROVEN demonstrates the mismatch origin; STRONG_CANDIDATE identifies the "
                "best-supported attribution still requiring a causal experiment."
            ),
            "replacement_semantics": (
                "Tracked separately from causal confidence; every current production "
                "replacement remains NOT_ESTABLISHED."
            ),
            "sanitization": (
                "Per-record leaf pseudonyms replace source identifiers; absolute source "
                "and STO coordinates are omitted; durations and lags are coarse classes."
            ),
        },
        "fixtures": fixtures,
        "controlled_repeat": {
            "project_build": TARGET_BUILD,
            "common_leaf_identities": summary.common_rows,
            "field_slots": summary.field_slots,
            "classifications": dict(summary.classifications),
            "unexpected_transition_differences": summary.unexpected_transition_count,
            "p1_g3_affected": False,
        },
        "baseline_matrix": {
            "mismatch_field_slots": len(inventory),
            "affected_leaf_identities": len(affected_source_uids),
            "by_field": dict(by_field),
            "dispositions": {
                "scheduled_activities": len(scheduled_uids),
                "excluded_activities": len(excluded_uids),
                "assumed_labelled_activities": len(assumed_activity_uids),
                "activity_exclusions_by_code": dict(
                    sorted(Counter(row.code for row in activity_exclusions).items())
                ),
            },
            "field_signatures": [
                {"fields": list(fields), "leaf_count": count}
                for fields, count in sorted(
                    signatures.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "graph_components": components,
        },
        "root_cause_groups": group_rows,
        "status_totals": {
            "PROVEN": status_slots["PROVEN"],
            "STRONG_CANDIDATE": status_slots["STRONG_CANDIDATE"],
            "UNKNOWN": status_slots["UNKNOWN"],
        },
        "activities": activity_context,
        "mismatches": public_inventory,
        "next_action": next_action,
        "gate": {
            "P1-G1": "PASS",
            "P1-G2": "OPEN",
            "P1-G3": "PASS",
            "P1-G4": "PASS",
            "P1-G5": "PASS",
            "P1": "4/5 IN PROGRESS",
            "P2": "NOT STARTED",
        },
    }


def canonical_json(record: Mapping[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=False) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="exact BOILER baseline XML")
    parser.add_argument("repeat", type=Path, help="exact UID 227 Project repeat XML")
    parser.add_argument(
        "--output",
        type=Path,
        help="write the deterministic JSON record instead of stdout",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fixtures = {"baseline": args.baseline, "repeat": args.repeat}
    if args.output is not None:
        refuse_output_alias(args.output, fixtures)
    serialized = canonical_json(build_record(args.baseline, args.repeat))
    if args.output is None:
        sys.stdout.write(serialized)
    else:
        write_output_safely(args.output, serialized, fixtures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
