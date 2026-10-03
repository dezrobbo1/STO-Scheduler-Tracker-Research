"""PL4's durable boundary around the S7 execution operation.

The project row lock serializes identity lookup, head movement and cursor
allocation. A transaction commits the immutable version, calculation, accepted
operation and movable head together; no in-memory notification is acceptance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable
from typing import Any

from sto.api.auth import ProjectAccess, lesser_role, role_allows
from sto.core.execution import ExecutionChange, ExecutionError, apply_execution, calculate_state
from sto.core.hashing import canonical_sha256
from sto.core.model.codec import encode_schedule
from sto.core.model.entities import SCHEMA_VERSION
from sto.persistence import auth_repositories as auth_repo
from sto.persistence import repositories as repo
from sto.scheduling.working_schedule import IntegrityError, Workspace, _verify


class LiveOperationRefused(ValueError):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ExecutionOperation:
    operation_id: uuid.UUID
    expected_version_id: uuid.UUID
    change: ExecutionChange


def semantic_payload(project_id: uuid.UUID, actor_user_id: uuid.UUID,
                     operation: ExecutionOperation) -> dict[str, Any]:
    """Versioned, parsed semantic values; wire whitespace and credentials do not bind."""
    change = operation.change
    return {
        "schema": 1, "kind": "execution", "project_id": str(project_id),
        "actor_user_id": str(actor_user_id),
        "expected_version_id": str(operation.expected_version_id),
        "expected_hash": change.expected_hash,
        "activity_uid": str(change.activity_uid),
        "actual_start": None if change.actual_start is None else change.actual_start.isoformat(),
        "actual_finish": None if change.actual_finish is None else change.actual_finish.isoformat(),
        "remaining_seconds": change.remaining_seconds,
    }


def receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": row["project_id"],
        "operation_id": row["operation_id"],
        "actor_user_id": row["actor_user_id"],
        "status": "applied",
        "server_sequence": row["server_sequence"],
        "accepted_at": row["accepted_at"],
        "base_version_id": row["base_version_id"],
        "result_version_id": row["result_version_id"],
        "calculation_id": row["calculation_id"],
        "canonical_hash": row["result_hash"],
        "result_fingerprint": row["result_fingerprint"],
        "execution": {
            key: row["semantic_payload"][key]
            for key in ("activity_uid", "actual_start", "actual_finish", "remaining_seconds")
        },
    }


def _checked_state(workspace: Workspace, project_id: uuid.UUID,
                   version: dict[str, Any], calculation_id: uuid.UUID):
    working = _verify(project_id, version)
    stored = workspace.read_calculation(project_id, calculation_id=calculation_id)
    if stored is None or stored.version_id != working.version_id:
        raise IntegrityError("live operation's base calculation does not name its base version")
    p = stored.result.provenance
    state = calculate_state(working.schedule, (p.horizon_start, p.horizon_finish),
                            epoch=p.epoch,
                            resource_calendars_apply=p.resource_calendars_apply)
    if state.canonical_hash != working.canonical_hash or state.result.fingerprint != stored.result.fingerprint:
        raise LiveOperationRefused("LIVE_CALCULATION_CONTEXT_CHANGED")
    return working, state


def _credential_still_valid(conn, access: ProjectAccess, now: datetime) -> bool:
    actor = access.actor
    if actor.authentication == "browser":
        row = conn.execute(
            "SELECT s.revoked_at, s.expires_at, u.enabled, s.user_id "
            "FROM server_sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id = %s FOR SHARE OF s",
            (actor.session_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT t.revoked_at, t.expires_at, u.enabled, t.user_id "
            "FROM device_tokens t JOIN users u ON u.id = t.user_id "
            "WHERE t.id = %s AND t.project_id = %s FOR SHARE OF t",
            (actor.device_token_id, access.project_id),
        ).fetchone()
    return bool(row is not None and row["user_id"] == actor.user_id
                and row["enabled"] and row["revoked_at"] is None
                and (row["expires_at"] is None or row["expires_at"] > now))


def submit(workspace: Workspace, project_id: uuid.UUID, access: ProjectAccess,
           operation: ExecutionOperation,
           *, auth_now: Callable[[], datetime]) -> tuple[dict[str, Any], bool]:
    """Return the durable receipt and whether this request created it."""
    actor = access.actor
    payload = semantic_payload(project_id, actor.user_id, operation)
    fingerprint = canonical_sha256(payload)
    with workspace.connect() as conn:
        if not repo.lock_project(conn, project_id):
            raise LiveOperationRefused("LIVE_PROJECT_UNKNOWN", 404)
        # Hold a shared credential row lock until commit. A logout, token
        # revocation or account disable cannot commit between this check and
        # the authoritative effect; a prior revocation is observed here.
        if not _credential_still_valid(conn, access, auth_now()):
            raise LiveOperationRefused("LIVE_CREDENTIAL_EXPIRED", 401)
        # Membership mutation also locks this project row. Check authority
        # inside the same serialized transaction, including on a retry.
        membership = auth_repo.get_membership(conn, project_id=project_id,
                                               user_id=actor.user_id)
        if membership is None or (actor.project_id is not None and actor.project_id != project_id):
            raise LiveOperationRefused("LIVE_PROJECT_UNKNOWN", 404)
        role = membership["role"]
        if actor.role_cap is not None:
            role = lesser_role(role, actor.role_cap)
        if not role_allows(role, "planner"):
            raise LiveOperationRefused("LIVE_EXECUTION_ROLE_REQUIRED", 403)

        existing = repo.live_operation(conn, project_id=project_id,
                                       operation_id=operation.operation_id)
        if existing is not None:
            if existing["semantic_fingerprint"] != fingerprint or existing["semantic_payload"] != payload:
                raise LiveOperationRefused("LIVE_OPERATION_ID_CONFLICT")
            return receipt(existing), False

        baseline = repo.head_version(conn, project_id=project_id, kind="baseline",
                                     with_document=False)
        if baseline is None:
            raise LiveOperationRefused("LIVE_BASELINE_REQUIRED")
        live = repo.head_version(conn, project_id=project_id, kind="live_working",
                                 with_document=False)
        base_id = live["id"] if live is not None else baseline["id"]
        if operation.expected_version_id != base_id:
            raise LiveOperationRefused("LIVE_STALE_HEAD")
        version = repo.get_version(conn, version_id=base_id, with_document=True)
        assert version is not None
        if version["canonical_hash"] != operation.change.expected_hash:
            raise LiveOperationRefused("LIVE_STALE_HEAD")
        base_calculation = repo.get_latest_calculation(conn, version_id=base_id)
        if base_calculation is None:
            raise LiveOperationRefused("LIVE_CALCULATION_REQUIRED")
        working, previous = _checked_state(workspace, project_id, version,
                                            base_calculation["id"])
        try:
            changed = apply_execution(previous, operation.change)
        except ExecutionError as error:
            raise LiveOperationRefused(error.code, 422) from error
        effect_id = uuid.uuid4()
        version_id = repo.insert_version(
            conn, project_id=project_id, kind="live_working",
            sequence=repo.next_sequence(conn, project_id), parent_id=working.version_id,
            canonical_hash=changed.canonical_hash, schema_version=SCHEMA_VERSION,
            cause_type="progress", cause_id=effect_id,
            document=encode_schedule(changed.schedule), identity_map=working.identity.to_dict(),
            created_by_user_id=actor.user_id,
        )
        calculation_id = repo.insert_calculation(
            conn, project_id=project_id, version_id=version_id,
            result=changed.result, created_by_user_id=actor.user_id,
        )
        if calculation_id is None:
            raise IntegrityError("new live version unexpectedly had a calculation")
        change_id = repo.insert_project_change(
            conn, project_id=project_id, source_id=effect_id,
            server_sequence=repo.live_cursor(conn, project_id) + 1,
        )
        row = repo.insert_live_operation(
            conn, effect_id=effect_id, project_id=project_id,
            operation_id=operation.operation_id,
            actor_user_id=actor.user_id, semantic_payload=payload,
            semantic_fingerprint=fingerprint, baseline_version_id=baseline["id"],
            base_version_id=base_id, base_calculation_id=base_calculation["id"],
            result_version_id=version_id, calculation_id=calculation_id,
            result_hash=changed.canonical_hash,
            result_fingerprint=changed.result.fingerprint,
            change_id=change_id,
        )
        if not _credential_still_valid(conn, access, auth_now()):
            raise LiveOperationRefused("LIVE_CREDENTIAL_EXPIRED", 401)
        repo.set_head(conn, project_id=project_id, kind="live_working", version_id=version_id)
        conn.commit()
        return receipt(row), True


def replay(workspace: Workspace, project_id: uuid.UUID) -> dict[str, Any]:
    """Independently fold committed S7 operations from the current baseline."""
    with workspace.connect() as conn:
        if not repo.lock_project(conn, project_id):
            raise LiveOperationRefused("LIVE_PROJECT_UNKNOWN", 404)
        baseline = repo.head_version(conn, project_id=project_id, kind="baseline",
                                     with_document=True)
        if baseline is None:
            raise LiveOperationRefused("LIVE_BASELINE_REQUIRED")
        live = repo.head_version(conn, project_id=project_id, kind="live_working",
                                 with_document=False)
        history = conn.execute(
            "SELECT o.*, c.server_sequence, c.kind, c.source_id "
            "FROM live_execution_operations o "
            "JOIN project_committed_changes c ON c.id = o.change_id "
            "WHERE o.project_id = %s AND o.baseline_version_id = %s "
            "ORDER BY c.server_sequence",
            (project_id, baseline["id"]),
        ).fetchall()
        base_id = baseline["id"]
        state = None
        for row in history:
            if (row["base_version_id"] != base_id or row["kind"] != "execution"
                    or row["source_id"] != row["id"]):
                raise IntegrityError("accepted execution history has a broken version chain")
            base_version = repo.get_version(conn, version_id=base_id, with_document=True)
            assert base_version is not None
            working, prior = _checked_state(workspace, project_id, base_version,
                                             row["base_calculation_id"])
            facts = row["semantic_payload"]
            if canonical_sha256(facts) != row["semantic_fingerprint"]:
                raise IntegrityError("accepted execution payload fingerprint changed")
            change = ExecutionChange(
                activity_uid=uuid.UUID(facts["activity_uid"]),
                expected_hash=facts["expected_hash"],
                actual_start=datetime.fromisoformat(facts["actual_start"]) if facts["actual_start"] else None,
                actual_finish=datetime.fromisoformat(facts["actual_finish"]) if facts["actual_finish"] else None,
                remaining_seconds=facts["remaining_seconds"],
            )
            if facts["project_id"] != str(project_id) or facts["expected_version_id"] != str(base_id):
                raise IntegrityError("accepted execution payload names a different project/base")
            state = apply_execution(prior, change)
            result_version = repo.get_version(conn, version_id=row["result_version_id"],
                                              with_document=True)
            if (result_version is None or result_version["parent_id"] != working.version_id
                    or result_version["project_id"] != project_id
                    or result_version["kind"] != "live_working"
                    or result_version["cause_type"] != "progress"
                    or result_version["cause_id"] != row["id"]
                    or _verify(project_id, result_version).canonical_hash != state.canonical_hash
                    or row["result_hash"] != state.canonical_hash
                    or row["result_fingerprint"] != state.result.fingerprint):
                raise IntegrityError("accepted execution effect does not reproduce its version/result")
            persisted = workspace.read_calculation(project_id, calculation_id=row["calculation_id"])
            if (persisted is None or persisted.version_id != row["result_version_id"]
                    or persisted.result.fingerprint != state.result.fingerprint):
                raise IntegrityError("accepted execution calculation differs from replay")
            base_id = row["result_version_id"]
        expected_head = baseline["id"] if live is None else live["id"]
        if base_id != expected_head:
            raise IntegrityError("replayed execution chain does not reach live head")
        digest = baseline["canonical_hash"] if state is None else state.canonical_hash
        return {
            "baseline_version_id": baseline["id"],
            "baseline_hash": _verify(project_id, baseline).canonical_hash,
            "operation_ids": [row["operation_id"] for row in history],
            "head_version_id": expected_head, "head_hash": digest,
            "replay_hash": digest, "equal": True,
        }
