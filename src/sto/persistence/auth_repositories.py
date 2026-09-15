"""SQL for authentication state. Cryptography stays at the API edge."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg


class LastProjectAdministrator(Exception):
    """A membership change would leave an enabled project with no admin."""


class DisabledUser(Exception):
    """A disabled account cannot receive active project authority."""


@dataclass(frozen=True, slots=True)
class DisableUserResult:
    changed: bool
    sessions_revoked: int
    device_tokens_revoked: int


def lock_bootstrap(conn: psycopg.Connection) -> None:
    """Serialize the one-time zero-user bootstrap decision."""

    conn.execute("SELECT pg_advisory_xact_lock(hashtext('sto-auth-bootstrap'))")


def count_users(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT count(*) AS count FROM users").fetchone()
    assert row is not None
    return int(row["count"])


def insert_user(
    conn: psycopg.Connection,
    *,
    username: str,
    normalized_username: str,
    display_name: str | None,
    password_hash: str,
    totp_secret_encrypted: bytes,
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO users
          (username, normalized_username, display_name, password_hash,
           totp_secret_encrypted)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, username, normalized_username, display_name, enabled, created_at
        """,
        (username, normalized_username, display_name, password_hash, totp_secret_encrypted),
    ).fetchone()
    assert row is not None
    return row


def get_user_by_username(
    conn: psycopg.Connection, normalized_username: str, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " FOR UPDATE" if for_update else ""
    return conn.execute(
        """
        SELECT id, username, normalized_username, display_name, password_hash,
               totp_secret_encrypted, last_totp_counter, enabled, created_at,
               password_changed_at, last_authenticated_at, disabled_at
        FROM users WHERE normalized_username = %s
        """ + lock,
        (normalized_username,),
    ).fetchone()


def get_user(
    conn: psycopg.Connection, user_id: uuid.UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " FOR UPDATE" if for_update else ""
    return conn.execute(
        """
        SELECT id, username, normalized_username, display_name, enabled, created_at,
               password_changed_at, last_authenticated_at, disabled_at
        FROM users WHERE id = %s
        """ + lock,
        (user_id,),
    ).fetchone()


def record_login(
    conn: psycopg.Connection,
    *,
    user_id: uuid.UUID,
    totp_counter: int,
    password_hash: str | None = None,
) -> None:
    if password_hash is None:
        conn.execute(
            """
            UPDATE users
            SET last_totp_counter = %s, last_authenticated_at = now()
            WHERE id = %s
            """,
            (totp_counter, user_id),
        )
    else:
        conn.execute(
            """
            UPDATE users
            SET last_totp_counter = %s, last_authenticated_at = now(),
                password_hash = %s, password_changed_at = now()
            WHERE id = %s
            """,
            (totp_counter, password_hash, user_id),
        )


def disable_user(conn: psycopg.Connection, user_id: uuid.UUID) -> DisableUserResult:
    """Disable one account without orphaning any project's administration.

    Membership grants, demotions, revocations and account disables share a
    short transaction-level lock. A disable can therefore lock every affected
    project in stable order, decide against committed authority, and invalidate
    both credential types atomically.
    """

    _lock_admin_state(conn)
    user = get_user(conn, user_id, for_update=True)
    if user is None:
        return DisableUserResult(False, 0, 0)
    if user["enabled"]:
        project_ids = [
            row["project_id"]
            for row in conn.execute(
                """
                SELECT project_id
                FROM project_memberships
                WHERE user_id = %s AND role = 'admin' AND revoked_at IS NULL
                ORDER BY project_id
                """,
                (user_id,),
            ).fetchall()
        ]
        for project_id in project_ids:
            _lock_project(conn, project_id)
        blocked = [
            project_id
            for project_id in project_ids
            if _other_enabled_admins(
                conn, project_id=project_id, user_id=user_id
            ) == 0
        ]
        if blocked:
            projects = ", ".join(str(project_id) for project_id in blocked)
            raise LastProjectAdministrator(
                "cannot disable the last enabled administrator for project(s) "
                f"{projects}; grant another enabled administrator or reassign "
                "the memberships first"
            )
        conn.execute(
            """
            UPDATE users SET enabled = FALSE, disabled_at = now()
            WHERE id = %s
            """,
            (user_id,),
        )
        changed = True
    else:
        changed = False
    sessions = revoke_user_sessions(conn, user_id)
    device_tokens = revoke_user_device_tokens(conn, user_id)
    return DisableUserResult(changed, sessions, device_tokens)


def grant_membership(
    conn: psycopg.Connection,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    created_by_user_id: uuid.UUID | None,
) -> dict[str, Any]:
    _lock_admin_state(conn)
    _lock_project(conn, project_id)
    user = get_user(conn, user_id, for_update=True)
    if user is None or not user["enabled"]:
        raise DisabledUser("project authority requires an enabled user")
    current = get_membership(
        conn, project_id=project_id, user_id=user_id, include_revoked=True
    )
    if (
        current is not None
        and current["revoked_at"] is None
        and current["role"] == "admin"
        and role != "admin"
        and _other_enabled_admins(conn, project_id=project_id, user_id=user_id) == 0
    ):
        raise LastProjectAdministrator("a project must retain an enabled administrator")
    row = conn.execute(
        """
        INSERT INTO project_memberships
          (project_id, user_id, role, created_by_user_id, updated_by_user_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (project_id, user_id)
        DO UPDATE SET role = EXCLUDED.role, revoked_at = NULL,
                      updated_at = now(),
                      updated_by_user_id = EXCLUDED.updated_by_user_id
        RETURNING project_id, user_id, role, created_at, created_by_user_id,
                  updated_at, updated_by_user_id, revoked_at
        """,
        (project_id, user_id, role, created_by_user_id, created_by_user_id),
    ).fetchone()
    assert row is not None
    return row


def get_membership(
    conn: psycopg.Connection,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    include_revoked: bool = False,
) -> dict[str, Any] | None:
    active = "" if include_revoked else " AND revoked_at IS NULL"
    return conn.execute(
        """
        SELECT project_id, user_id, role, created_at, created_by_user_id,
               updated_at, updated_by_user_id, revoked_at
        FROM project_memberships WHERE project_id = %s AND user_id = %s
        """ + active,
        (project_id, user_id),
    ).fetchone()


def revoke_membership(
    conn: psycopg.Connection,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> dict[str, Any] | None:
    _lock_admin_state(conn)
    _lock_project(conn, project_id)
    current = get_membership(conn, project_id=project_id, user_id=user_id)
    if current is None:
        return None
    if (
        current["role"] == "admin"
        and _other_enabled_admins(conn, project_id=project_id, user_id=user_id) == 0
    ):
        raise LastProjectAdministrator("a project must retain an enabled administrator")
    row = conn.execute(
        """
        UPDATE project_memberships
        SET revoked_at = now(), updated_at = now(), updated_by_user_id = %s
        WHERE project_id = %s AND user_id = %s AND revoked_at IS NULL
        RETURNING project_id, user_id, role, created_at, created_by_user_id,
                  updated_at, updated_by_user_id, revoked_at
        """,
        (actor_user_id, project_id, user_id),
    ).fetchone()
    conn.execute(
        """
        UPDATE device_tokens
        SET revoked_at = GREATEST(clock_timestamp(), issued_at)
        WHERE project_id = %s AND user_id = %s AND revoked_at IS NULL
        """,
        (project_id, user_id),
    )
    return row


def _lock_project(conn: psycopg.Connection, project_id: uuid.UUID) -> None:
    row = conn.execute(
        "SELECT id FROM projects WHERE id = %s FOR UPDATE", (project_id,)
    ).fetchone()
    if row is None:
        raise ValueError("no such project")


def _lock_admin_state(conn: psycopg.Connection) -> None:
    """Serialize the bounded set of account/project authority transitions."""

    conn.execute("SELECT pg_advisory_xact_lock(hashtext('sto-auth-admin-state'))")


def _other_enabled_admins(
    conn: psycopg.Connection, *, project_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    row = conn.execute(
        """
        SELECT count(*) AS count
        FROM project_memberships m
        JOIN users u ON u.id = m.user_id
        WHERE m.project_id = %s AND m.user_id <> %s
          AND m.role = 'admin' AND m.revoked_at IS NULL AND u.enabled
        """,
        (project_id, user_id),
    ).fetchone()
    assert row is not None
    return int(row["count"])


def list_memberships(
    conn: psycopg.Connection, *, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT m.project_id, m.user_id, m.role, m.created_at,
               u.username, u.display_name, u.enabled
        FROM project_memberships m
        JOIN users u ON u.id = m.user_id
        WHERE m.project_id = %s AND m.revoked_at IS NULL
        ORDER BY u.normalized_username, u.id
        """,
        (project_id,),
    ).fetchall()


def insert_session(
    conn: psycopg.Connection,
    *,
    user_id: uuid.UUID,
    token_hash: str,
    token_prefix: str,
    expires_at: datetime,
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO server_sessions (user_id, token_hash, token_prefix, expires_at)
        VALUES (%s, %s, %s, %s)
        RETURNING id, user_id, token_prefix, issued_at, expires_at
        """,
        (user_id, token_hash, token_prefix, expires_at),
    ).fetchone()
    assert row is not None
    return row


def get_session_by_hash(conn: psycopg.Connection, token_hash: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT s.id, s.user_id, s.token_prefix, s.issued_at, s.expires_at,
               s.last_seen_at, s.revoked_at,
               u.username, u.display_name, u.enabled
        FROM server_sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = %s
        """,
        (token_hash,),
    ).fetchone()


def revoke_session(conn: psycopg.Connection, session_id: uuid.UUID) -> bool:
    row = conn.execute(
        """
        UPDATE server_sessions
        SET revoked_at = GREATEST(clock_timestamp(), issued_at)
        WHERE id = %s AND revoked_at IS NULL
        RETURNING id
        """,
        (session_id,),
    ).fetchone()
    return row is not None


def revoke_session_by_hash(conn: psycopg.Connection, token_hash: str) -> bool:
    row = conn.execute(
        """
        UPDATE server_sessions
        SET revoked_at = GREATEST(clock_timestamp(), issued_at)
        WHERE token_hash = %s AND revoked_at IS NULL
        RETURNING id
        """,
        (token_hash,),
    ).fetchone()
    return row is not None


def revoke_user_sessions(conn: psycopg.Connection, user_id: uuid.UUID) -> int:
    cursor = conn.execute(
        """
        UPDATE server_sessions
        SET revoked_at = GREATEST(clock_timestamp(), issued_at)
        WHERE user_id = %s AND revoked_at IS NULL
        """,
        (user_id,),
    )
    return cursor.rowcount


def revoke_user_device_tokens(conn: psycopg.Connection, user_id: uuid.UUID) -> int:
    cursor = conn.execute(
        """
        UPDATE device_tokens
        SET revoked_at = GREATEST(clock_timestamp(), issued_at)
        WHERE user_id = %s AND revoked_at IS NULL
        """,
        (user_id,),
    )
    return cursor.rowcount


def insert_device_token(
    conn: psycopg.Connection,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    role: str,
    token_hash: str,
    token_prefix: str,
    expires_at: datetime | None,
    issued_by_user_id: uuid.UUID,
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO device_tokens
          (user_id, project_id, role, token_hash, token_prefix, expires_at,
           issued_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, user_id, project_id, role, token_prefix, issued_at,
                  expires_at, revoked_at, issued_by_user_id
        """,
        (
            user_id,
            project_id,
            role,
            token_hash,
            token_prefix,
            expires_at,
            issued_by_user_id,
        ),
    ).fetchone()
    assert row is not None
    return row


def get_device_token_by_hash(
    conn: psycopg.Connection, token_hash: str
) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT t.id, t.user_id, t.project_id, t.role AS token_role,
               t.token_prefix, t.issued_at, t.expires_at, t.revoked_at,
               u.username, u.display_name, u.enabled,
               m.role AS membership_role
        FROM device_tokens t
        JOIN users u ON u.id = t.user_id
        JOIN project_memberships m
          ON m.project_id = t.project_id AND m.user_id = t.user_id
        WHERE t.token_hash = %s AND m.revoked_at IS NULL
        """,
        (token_hash,),
    ).fetchone()


def list_device_tokens(
    conn: psycopg.Connection, *, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT t.id, t.user_id, t.project_id, t.role, t.token_prefix,
               t.issued_at, t.expires_at, t.revoked_at, t.issued_by_user_id,
               u.username, u.display_name
        FROM device_tokens t JOIN users u ON u.id = t.user_id
        WHERE t.project_id = %s
        ORDER BY t.issued_at, t.id
        """,
        (project_id,),
    ).fetchall()


def revoke_device_token(
    conn: psycopg.Connection, *, project_id: uuid.UUID, token_id: uuid.UUID
) -> bool:
    row = conn.execute(
        """
        UPDATE device_tokens
        SET revoked_at = GREATEST(clock_timestamp(), issued_at)
        WHERE id = %s AND project_id = %s AND revoked_at IS NULL
        RETURNING id
        """,
        (token_id, project_id),
    ).fetchone()
    return row is not None
