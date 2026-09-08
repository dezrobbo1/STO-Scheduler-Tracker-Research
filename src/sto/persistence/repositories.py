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


def get_version(
    conn: psycopg.Connection, *, version_id: uuid.UUID, with_document: bool
) -> dict[str, Any] | None:
    """One version by identifier, whatever head points at it."""

    columns = _VERSION_SUMMARY + (", v.document, v.identity_map" if with_document else "")
    return conn.execute(
        f"SELECT {columns} FROM schedule_versions v WHERE v.id = %s",
        (version_id,),
    ).fetchone()


def heads_for_all_projects(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        f"""
        SELECT h.kind AS head_kind, {_VERSION_SUMMARY}
        FROM schedule_heads h JOIN schedule_versions v ON v.id = h.version_id
        ORDER BY v.project_id, h.kind
        """
    ).fetchall()


# --- calculated results --------------------------------------------------------


def insert_calculation(
    conn: psycopg.Connection,
    *,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    result: Any,
) -> uuid.UUID | None:
    """Store one engine run: the header, then its rows, or ``None``.

    ``None`` means an identical run was already stored -- same version, same
    fingerprint -- which the unique constraint enforces and which two
    overlapping callers can both reach. The caller looks the winner up.

    Written in one statement per table rather than one per row: a real schedule
    is a couple of thousand activities, and the caller holds a transaction
    open around this.
    """

    provenance = result.provenance
    row = conn.execute(
        """
        INSERT INTO schedule_calculations
          (project_id, version_id, canonical_hash, result_fingerprint, epoch,
           horizon_start, horizon_finish, progress_policy,
           critical_float_threshold, status_time, status_time_outside_window,
           resource_calendars_apply, relationship_dispositions, profiles)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (version_id, result_fingerprint) DO NOTHING
        RETURNING id
        """,
        (
            project_id,
            version_id,
            provenance.canonical_hash,
            result.fingerprint,
            provenance.epoch,
            provenance.horizon_start,
            provenance.horizon_finish,
            provenance.progress_policy,
            provenance.critical_float_threshold,
            provenance.status_time,
            provenance.status_time_outside_window,
            provenance.resource_calendars_apply,
            Jsonb(
                [
                    {
                        "uid": str(edge.uid),
                        "disposition": edge.disposition,
                        "code": edge.code,
                        "detail": edge.detail,
                    }
                    for edge in result.relationships
                ]
            ),
            Jsonb(
                {
                    "forward": provenance.forward_profile,
                    "backward": provenance.backward_profile,
                    "criticality": provenance.criticality_profile,
                    "rollup": provenance.rollup_profile,
                    "progress": provenance.progress_profile,
                    "result": provenance.result_profile,
                }
            ),
        ),
    ).fetchone()
    if row is None:
        # Another caller stored this exact answer between any lookup and here.
        # A calculation is deterministic, so the row that won is the row this
        # one would have written; the race is not an error.
        return None
    calculation_id = row["id"]

    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO activity_results
              (calculation_id, activity_uid, disposition, early_start, early_finish,
               late_start, late_finish, remaining_start, total_float_seconds,
               free_float_seconds, start_float_seconds, finish_float_seconds,
               critical, progress_state, placed_by,
               driving_relationship_uid, late_placed_by,
               late_driving_relationship_uid, constraint_override,
               exclusion_code, exclusion_detail, assumptions)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    calculation_id,
                    activity.uid,
                    activity.disposition,
                    activity.early_start,
                    activity.early_finish,
                    activity.late_start,
                    activity.late_finish,
                    activity.remaining_start,
                    activity.total_float,
                    activity.free_float,
                    activity.start_float,
                    activity.finish_float,
                    activity.critical,
                    activity.state,
                    activity.placed_by,
                    activity.driving_relationship_uid,
                    activity.late_placed_by,
                    activity.late_driving_relationship_uid,
                    activity.constraint_override,
                    activity.exclusion_code,
                    activity.exclusion_detail,
                    list(activity.assumptions),
                )
                for activity in result.activities
            ],
        )
        rows = [
            (calculation_id, summary.uid, summary.start, summary.finish, summary.placed)
            for summary in result.summaries
        ]
        # A branch with nothing beneath it is stored as a row with no span, so
        # that "not calculated" and "not in the file" stay different answers.
        rows += [(calculation_id, uid, None, None, 0) for uid in result.empty_summaries]
        cursor.executemany(
            """
            INSERT INTO summary_results
              (calculation_id, wbs_uid, span_start, span_finish, placed)
            VALUES (%s, %s, %s, %s, %s)
            """,
            rows,
        )
    return calculation_id


def list_import_batches(
    conn: psycopg.Connection, *, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every parser run against a project, newest last. Failures included."""

    return conn.execute(
        """
        SELECT * FROM import_batches
        WHERE project_id = %s
        ORDER BY started_at, id
        """,
        (project_id,),
    ).fetchall()


def get_latest_calculation(
    conn: psycopg.Connection, *, version_id: uuid.UUID
) -> dict[str, Any] | None:
    """The most recent run over one version, header only."""

    return conn.execute(
        """
        SELECT * FROM schedule_calculations
        WHERE version_id = %s
        ORDER BY computed_at DESC, id DESC
        LIMIT 1
        """,
        (version_id,),
    ).fetchone()


def find_calculation(
    conn: psycopg.Connection, *, version_id: uuid.UUID, fingerprint: str
) -> dict[str, Any] | None:
    """The calculation already stored for this version under this fingerprint.

    A calculation is deterministic, so the same version computed the same way
    twice is the same answer. The table holds it once; this is how a caller
    finds the one that is there instead of colliding with it.
    """

    return conn.execute(
        """
        SELECT * FROM schedule_calculations
        WHERE version_id = %s AND result_fingerprint = %s
        """,
        (version_id, fingerprint),
    ).fetchone()


def get_calculation(
    conn: psycopg.Connection, *, calculation_id: uuid.UUID
) -> dict[str, Any] | None:
    """One calculation header by identifier."""

    return conn.execute(
        "SELECT * FROM schedule_calculations WHERE id = %s",
        (calculation_id,),
    ).fetchone()


def get_activity_results(
    conn: psycopg.Connection, *, calculation_id: uuid.UUID
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT * FROM activity_results
        WHERE calculation_id = %s
        ORDER BY activity_uid
        """,
        (calculation_id,),
    ).fetchall()


def get_summary_results(
    conn: psycopg.Connection, *, calculation_id: uuid.UUID
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT * FROM summary_results
        WHERE calculation_id = %s
        ORDER BY wbs_uid
        """,
        (calculation_id,),
    ).fetchall()
