"""Small PL5 communication/media device-trial seam, separate from S7.

PL15 owns the permanent domain. These accepted trial facts use PL4's project
cursor and current authority but never enter canonical schedule documents.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Callable

from psycopg.types.json import Jsonb

from sto.api.auth import ProjectAccess, lesser_role, role_allows
from sto.persistence import auth_repositories as auth_repo
from sto.persistence import repositories as repo
from sto.scheduling.live_operations import _credential_still_valid, receipt as execution_receipt
from sto.scheduling.working_schedule import Workspace, _verify


class TrialRefused(ValueError):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def _fingerprint(payload: dict[str, Any]) -> str:
    # Trial annotation coordinates are bounded floats. The canonical schedule
    # has an integer-only hash; it must not be reused for media payloads.
    value = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _authority(conn, access: ProjectAccess, now: Callable[[], datetime]) -> None:
    auth_repo.lock_auth_state_for_acceptance(conn)
    if not _credential_still_valid(conn, access, now()):
        raise TrialRefused("TRIAL_CREDENTIAL_EXPIRED", 401)
    if not repo.lock_project(conn, access.project_id):
        raise TrialRefused("TRIAL_PROJECT_UNKNOWN", 404)
    membership = auth_repo.get_membership(conn, project_id=access.project_id,
                                          user_id=access.actor.user_id)
    if membership is None or (access.actor.project_id is not None
                              and access.actor.project_id != access.project_id):
        raise TrialRefused("TRIAL_PROJECT_UNKNOWN", 404)
    role = membership["role"]
    if access.actor.role_cap is not None:
        role = lesser_role(role, access.actor.role_cap)
    # The trial does not invent a new field/communication capability.
    if not role_allows(role, "planner"):
        raise TrialRefused("TRIAL_ROLE_REQUIRED", 403)


def _current_activity(conn, project_id: uuid.UUID, activity_uid: uuid.UUID) -> uuid.UUID:
    version = repo.head_version(conn, project_id=project_id, kind="live_working",
                                with_document=True)
    if version is None:
        version = repo.head_version(conn, project_id=project_id, kind="baseline",
                                    with_document=True)
    if version is None:
        raise TrialRefused("TRIAL_SCHEDULE_REQUIRED")
    schedule = _verify(project_id, version).schedule
    if activity_uid not in {activity.uid for activity in schedule.activities}:
        raise TrialRefused("TRIAL_ACTIVITY_UNKNOWN", 422)
    return version["id"]


def _change(conn, project_id: uuid.UUID, kind: str, source_id: uuid.UUID) -> uuid.UUID:
    row = conn.execute(
        "INSERT INTO project_committed_changes(project_id,server_sequence,kind,source_id) "
        "VALUES (%s,%s,%s,%s) RETURNING id",
        (project_id, repo.live_cursor(conn, project_id) + 1, kind, source_id),
    ).fetchone()
    assert row is not None
    return row["id"]


def message_receipt(conn, project_id: uuid.UUID, message_id: uuid.UUID) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT m.*,c.server_sequence,c.accepted_at FROM pl5_trial_messages m "
        "JOIN project_committed_changes c ON c.id=m.change_id "
        "WHERE m.project_id=%s AND m.id=%s", (project_id, message_id),
    ).fetchone()
    if row is None:
        return None
    return {"kind": "trial_message", "id": row["id"], "project_id": project_id,
            "actor_user_id": row["actor_user_id"], "activity_uid": row["activity_uid"],
            "version_id": row["version_id"], "text": row["body"],
            "server_sequence": row["server_sequence"], "accepted_at": row["accepted_at"],
            "status": "accepted"}


def submit_message(workspace: Workspace, access: ProjectAccess, *, message_id: uuid.UUID,
                   activity_uid: uuid.UUID, text: str,
                   auth_now: Callable[[], datetime]) -> tuple[dict[str, Any], bool]:
    project = access.project_id
    fingerprint = _fingerprint({"schema": 1, "kind": "trial_message",
        "project_id": str(project), "actor_user_id": str(access.actor.user_id),
        "activity_uid": str(activity_uid), "text": text})
    with workspace.connect() as conn:
        _authority(conn, access, auth_now)
        old = conn.execute("SELECT semantic_fingerprint FROM pl5_trial_messages "
                           "WHERE project_id=%s AND id=%s", (project, message_id)).fetchone()
        if old is not None:
            if old["semantic_fingerprint"] != fingerprint:
                raise TrialRefused("TRIAL_ID_CONFLICT")
            result = message_receipt(conn, project, message_id)
            assert result is not None
            return result, False
        if not text.strip() or len(text) > 2000:
            raise TrialRefused("TRIAL_TEXT_INVALID", 422)
        version_id = _current_activity(conn, project, activity_uid)
        change_id = _change(conn, project, "trial_message", message_id)
        conn.execute(
            "INSERT INTO pl5_trial_messages "
            "(id,project_id,actor_user_id,activity_uid,version_id,body,semantic_fingerprint,change_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (message_id, project, access.actor.user_id, activity_uid, version_id,
             text, fingerprint, change_id),
        )
        if not _credential_still_valid(conn, access, auth_now()):
            raise TrialRefused("TRIAL_CREDENTIAL_EXPIRED", 401)
        result = message_receipt(conn, project, message_id)
        conn.commit()
        assert result is not None
        return result, True


def media_receipt(conn, project_id: uuid.UUID, media_id: uuid.UUID) -> dict[str, Any] | None:
    row = conn.execute("SELECT id,project_id,actor_user_id,activity_uid,mime,sha256,"
                       "annotations,uploaded_at FROM pl5_trial_media WHERE project_id=%s AND id=%s",
                       (project_id, media_id)).fetchone()
    if row is None:
        return None
    link = conn.execute("SELECT l.message_id,c.server_sequence FROM pl5_trial_media_links l "
                        "JOIN project_committed_changes c ON c.id=l.change_id "
                        "WHERE l.project_id=%s AND l.media_id=%s",
                        (project_id, media_id)).fetchone()
    return {**row, "kind": "trial_media", "status": "linked" if link else "uploaded",
            "message_id": link["message_id"] if link else None,
            "server_sequence": link["server_sequence"] if link else None}


def upload_media(workspace: Workspace, access: ProjectAccess, *, media_id: uuid.UUID,
                 activity_uid: uuid.UUID, mime: str, original: bytes, sha256: str,
                 annotations: list[dict[str, Any]],
                 auth_now: Callable[[], datetime]) -> tuple[dict[str, Any], bool]:
    project = access.project_id
    if mime not in {"image/jpeg", "image/png"} or not 1 <= len(original) <= 5 * 1024 * 1024:
        raise TrialRefused("TRIAL_MEDIA_INVALID", 422)
    if hashlib.sha256(original).hexdigest() != sha256:
        raise TrialRefused("TRIAL_MEDIA_HASH_MISMATCH", 422)
    fingerprint = _fingerprint({"schema": 1, "kind": "trial_media",
        "project_id": str(project), "actor_user_id": str(access.actor.user_id),
        "activity_uid": str(activity_uid), "mime": mime, "sha256": sha256,
        "annotations": annotations})
    with workspace.connect() as conn:
        _authority(conn, access, auth_now)
        old = conn.execute("SELECT semantic_fingerprint FROM pl5_trial_media "
                           "WHERE project_id=%s AND id=%s", (project, media_id)).fetchone()
        if old is not None:
            if old["semantic_fingerprint"] != fingerprint:
                raise TrialRefused("TRIAL_MEDIA_ID_CONFLICT")
            result = media_receipt(conn, project, media_id)
            assert result is not None
            return result, False
        _current_activity(conn, project, activity_uid)
        conn.execute("INSERT INTO pl5_trial_media "
                     "(id,project_id,actor_user_id,activity_uid,mime,original,sha256,annotations,semantic_fingerprint) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (media_id, project, access.actor.user_id, activity_uid, mime,
                      original, sha256, Jsonb(annotations), fingerprint))
        if not _credential_still_valid(conn, access, auth_now()):
            raise TrialRefused("TRIAL_CREDENTIAL_EXPIRED", 401)
        result = media_receipt(conn, project, media_id)
        conn.commit()
        assert result is not None
        return result, True


def link_media(workspace: Workspace, access: ProjectAccess, *, media_id: uuid.UUID,
               message_id: uuid.UUID,
               auth_now: Callable[[], datetime]) -> tuple[dict[str, Any], bool]:
    project = access.project_id
    with workspace.connect() as conn:
        _authority(conn, access, auth_now)
        media = conn.execute("SELECT actor_user_id,activity_uid FROM pl5_trial_media "
                             "WHERE project_id=%s AND id=%s", (project, media_id)).fetchone()
        message = conn.execute("SELECT actor_user_id,activity_uid FROM pl5_trial_messages "
                               "WHERE project_id=%s AND id=%s", (project, message_id)).fetchone()
        if media is None or message is None:
            raise TrialRefused("TRIAL_LINK_TARGET_UNKNOWN", 404)
        if (media["actor_user_id"] != access.actor.user_id or
            message["actor_user_id"] != access.actor.user_id or
            media["activity_uid"] != message["activity_uid"]):
            raise TrialRefused("TRIAL_LINK_MISMATCH", 403)
        existing = conn.execute("SELECT message_id FROM pl5_trial_media_links "
                                "WHERE project_id=%s AND media_id=%s", (project, media_id)).fetchone()
        if existing is not None:
            if existing["message_id"] != message_id:
                raise TrialRefused("TRIAL_LINK_CONFLICT")
            result = media_receipt(conn, project, media_id)
            assert result is not None
            return result, False
        link_id = uuid.uuid4()
        change_id = _change(conn, project, "trial_media_link", link_id)
        conn.execute("INSERT INTO pl5_trial_media_links "
                     "(id,project_id,media_id,message_id,actor_user_id,change_id) "
                     "VALUES (%s,%s,%s,%s,%s,%s)",
                     (link_id, project, media_id, message_id, access.actor.user_id, change_id))
        if not _credential_still_valid(conn, access, auth_now()):
            raise TrialRefused("TRIAL_CREDENTIAL_EXPIRED", 401)
        result = media_receipt(conn, project, media_id)
        conn.commit()
        assert result is not None
        return result, True


def change_feed(conn, project_id: uuid.UUID, after: int, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT kind,source_id FROM project_committed_changes "
                        "WHERE project_id=%s AND server_sequence>%s "
                        "ORDER BY server_sequence LIMIT %s", (project_id, after, limit)).fetchall()
    events = []
    for row in rows:
        kind, source_id = row["kind"], row["source_id"]
        if kind == "execution":
            operation = conn.execute("SELECT o.*,c.server_sequence,c.accepted_at "
                "FROM live_execution_operations o JOIN project_committed_changes c ON c.id=o.change_id "
                "WHERE o.project_id=%s AND o.id=%s", (project_id, source_id)).fetchone()
            if operation is None:
                raise RuntimeError("committed execution change has no operation")
            events.append(execution_receipt(operation))
        elif kind == "trial_message":
            event = message_receipt(conn, project_id, source_id)
            if event is None:
                raise RuntimeError("committed trial message change has no message")
            events.append(event)
        elif kind == "trial_media_link":
            link = conn.execute("SELECT l.*,c.server_sequence,c.accepted_at "
                "FROM pl5_trial_media_links l JOIN project_committed_changes c ON c.id=l.change_id "
                "WHERE l.project_id=%s AND l.id=%s", (project_id, source_id)).fetchone()
            if link is None:
                raise RuntimeError("committed media link has no domain row")
            events.append({"kind": kind, "id": link["id"], "project_id": project_id,
                "media_id": link["media_id"], "message_id": link["message_id"],
                "server_sequence": link["server_sequence"], "accepted_at": link["accepted_at"]})
        else:
            raise RuntimeError("unsupported committed change kind")
    return events
