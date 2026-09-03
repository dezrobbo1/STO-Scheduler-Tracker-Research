"""Rows in, rows out. Every function takes the connection; the caller commits.

Kept as plain functions rather than a repository class per table: the SQL is
the interface, and a function per statement keeps it readable in one place.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

VERSION_KINDS = ("baseline", "approved_forecast", "live_working", "scenario")
CAUSE_TYPES = ("import", "progress", "planner_edit", "review", "promotion")
IMPORT_STATUSES = ("pending", "parsing", "parsed", "accepted", "failed", "superseded")


# --- projects ------------------------------------------------------------------


def create_project(
    conn: psycopg.Connection,
    *,
    name: str,
    timezone: str = "UTC",
    description: str | None = None,
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO projects (name, timezone, description)
        VALUES (%s, %s, %s)
        RETURNING id, name, description, status, timezone, created_at, updated_at
        """,
        (name, timezone, description),
    ).fetchone()
    assert row is not None
    return row


def get_project(conn: psycopg.Connection, project_id: uuid.UUID) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id, name, description, status, timezone, created_at, updated_at"
        " FROM projects WHERE id = %s",
        (project_id,),
    ).fetchone()


def list_projects(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT id, name, description, status, timezone, created_at, updated_at"
        " FROM projects ORDER BY created_at, id"
    ).fetchall()


# --- source files and import batches ------------------------------------------


def insert_source_file(
    conn: psycopg.Connection,
    *,
    project_id: uuid.UUID,
    original_filename: str,
    file_kind: str,
    storage_uri: str,
    content_hash: str,
    size_bytes: int,
) -> uuid.UUID:
    row = conn.execute(
        """
        INSERT INTO source_files
          (project_id, original_filename, file_kind, storage_uri, content_hash, size_bytes)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (project_id, original_filename, file_kind, storage_uri, content_hash, size_bytes),
    ).fetchone()
    assert row is not None
    return row["id"]


def insert_import_batch(
    conn: psycopg.Connection,
    *,
    project_id: uuid.UUID,
    source_file_id: uuid.UUID,
    status: str,
    parser_name: str,
    parser_version: str,
    parse_summary: dict[str, Any],
    warning_count: int = 0,
    error_count: int = 0,
) -> uuid.UUID:
    row = conn.execute(
        """
        INSERT INTO import_batches
          (project_id, source_file_id, status, parser_name, parser_version,
           started_at, completed_at, warning_count, error_count, parse_summary)
        VALUES (%s, %s, %s, %s, %s, now(), now(), %s, %s, %s)
        RETURNING id
        """,
        (
            project_id,
            source_file_id,
            status,
            parser_name,
            parser_version,
            warning_count,
            error_count,
            Jsonb(parse_summary),
        ),
    ).fetchone()
    assert row is not None
    return row["id"]


# --- schedule versions and heads ----------------------------------------------


def next_sequence(conn: psycopg.Connection, project_id: uuid.UUID) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM schedule_versions WHERE project_id = %s",
        (project_id,),
    ).fetchone()
    assert row is not None
    return int(row["next"])


def insert_version(
    conn: psycopg.Connection,
    *,
    project_id: uuid.UUID,
    kind: str,
    sequence: int,
    parent_id: uuid.UUID | None,
    canonical_hash: str,
    schema_version: str,
    cause_type: str,
    cause_id: uuid.UUID | None,
    document: dict[str, Any],
    identity_map: dict[str, Any],
) -> uuid.UUID:
    row = conn.execute(
        """
        INSERT INTO schedule_versions
          (project_id, kind, sequence, parent_id, canonical_hash, schema_version,
           cause_type, cause_id, document, identity_map)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            project_id,
            kind,
            sequence,
            parent_id,
            canonical_hash,
            schema_version,
            cause_type,
            cause_id,
            Jsonb(document),
            Jsonb(identity_map),
        ),
    ).fetchone()
    assert row is not None
    return row["id"]


def set_head(
    conn: psycopg.Connection, *, project_id: uuid.UUID, kind: str, version_id: uuid.UUID
) -> None:
    conn.execute(
        """
        INSERT INTO schedule_heads (project_id, kind, version_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (project_id, kind)
        DO UPDATE SET version_id = EXCLUDED.version_id, updated_at = now()
        """,
        (project_id, kind, version_id),
    )


_VERSION_SUMMARY = (
    "v.id, v.project_id, v.kind, v.sequence, v.parent_id, v.canonical_hash,"
    " v.schema_version, v.engine_profile, v.cause_type, v.cause_id, v.created_at"
)


def head_version(
    conn: psycopg.Connection, *, project_id: uuid.UUID, kind: str, with_document: bool
) -> dict[str, Any] | None:
    columns = _VERSION_SUMMARY + (", v.document, v.identity_map" if with_document else "")
    return conn.execute(
        f"""
        SELECT {columns}
        FROM schedule_heads h JOIN schedule_versions v ON v.id = h.version_id
        WHERE h.project_id = %s AND h.kind = %s
        """,
        (project_id, kind),
    ).fetchone()


def list_versions(conn: psycopg.Connection, *, project_id: uuid.UUID) -> list[dict[str, Any]]:
    return conn.execute(
        f"SELECT {_VERSION_SUMMARY} FROM schedule_versions v"
        " WHERE v.project_id = %s ORDER BY v.sequence",
        (project_id,),
    ).fetchall()


def heads_for_all_projects(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        f"""
        SELECT h.kind AS head_kind, {_VERSION_SUMMARY}
        FROM schedule_heads h JOIN schedule_versions v ON v.id = h.version_id
        ORDER BY v.project_id, h.kind
        """
    ).fetchall()
