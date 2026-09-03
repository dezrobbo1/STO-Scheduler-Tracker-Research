"""One resident schedule per project, and the import that produces one.

The database holds immutable versions and a movable head. This holds the head's
document decoded, so that a request does not decode 14 MB of JSON every time
and so that, when the engine arrives, the graph it needs is already resident.

Two rules that the persistence gate rests on:

* A version's ``canonical_hash`` is computed from the canonical bytes *before*
  the row is written, and **recomputed from the stored document on every
  load**. If PostgreSQL's JSONB round trip ever changed a value, the load fails
  rather than serving a document whose hash is a lie.
* A later import into the same project reconciles against the identity map of
  the current baseline, so the rows that survived keep their identifiers. The
  project is the operator's statement that these files are the same shutdown;
  a differing declared project GUID is recorded on the import, not refused --
  the two real BOILER snapshots differ exactly that way.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from sto.core.hashing import canonical_sha256
from sto.core.model import IdentityMap, ReconciliationReport, Schedule, decode_schedule
from sto.core.model.codec import encode_schedule
from sto.core.model.entities import SCHEMA_VERSION
from sto.core.model.ids import normalise_guid
from sto.core.model.migrate.sto_v011 import MigrationError, migrate
from sto.legacy import import_mspdi
from sto.persistence import repositories as repo

PARSER_NAME = "sto.legacy.import_mspdi"
PARSER_VERSION = "0.1.1"


class IntegrityError(RuntimeError):
    """A stored version does not hash to what it says it hashes to."""


class UnknownProject(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class WorkingSchedule:
    project_id: uuid.UUID
    version_id: uuid.UUID
    sequence: int
    canonical_hash: str
    schedule: Schedule
    identity: IdentityMap


@dataclass(frozen=True, slots=True)
class ImportResult:
    project_id: uuid.UUID
    import_batch_id: uuid.UUID
    version_id: uuid.UUID
    sequence: int
    canonical_hash: str
    source_sha256: str
    reconciliation: ReconciliationReport
    project_identity_mismatch: bool
    declared_project_guid: str | None


def default_source_dir() -> Path:
    configured = os.environ.get("STO_SOURCE_DIR")
    if configured:
        return Path(configured)
    return Path.home() / ".local" / "share" / "sto" / "source-files"


@dataclass
class Workspace:
    """Every project's resident head, loaded lazily and verified on load."""

    connect: Callable[[], psycopg.Connection]
    source_dir: Path = field(default_factory=default_source_dir)
    _resident: dict[uuid.UUID, WorkingSchedule] = field(default_factory=dict)
    #: Projects whose head failed verification at the last rebuild, with why.
    #: They are not resident; health reports them; their routes return 500.
    integrity_failures: dict[uuid.UUID, str] = field(default_factory=dict)

    # --- reading ---------------------------------------------------------------

    def rebuild(self) -> int:
        """Load and verify every project's baseline head. Called at boot.

        A version that does not hash to what it says is not served and is
        not fatal to the process: the other projects are fine, and a boot
        that refused entirely would hide which one is not. It is reported by
        ``/api/health`` and by that project's own routes.
        """

        self._resident.clear()
        self.integrity_failures.clear()
        with self.connect() as conn:
            heads = repo.heads_for_all_projects(conn)
        for head in heads:
            if head["head_kind"] != "baseline":
                continue
            try:
                self.load(head["project_id"])
            except IntegrityError as error:
                self.integrity_failures[head["project_id"]] = str(error)
        return len(self._resident)

    def resident_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(self._resident)

    def load(self, project_id: uuid.UUID) -> WorkingSchedule | None:
        cached = self._resident.get(project_id)
        if cached is not None:
            return cached
        with self.connect() as conn:
            if repo.get_project(conn, project_id) is None:
                raise UnknownProject(str(project_id))
            row = repo.head_version(
                conn, project_id=project_id, kind="baseline", with_document=True
            )
        if row is None:
            return None
        try:
            working = _verify(project_id, row)
        except IntegrityError as error:
            self.integrity_failures[project_id] = str(error)
            raise
        self.integrity_failures.pop(project_id, None)
        self._resident[project_id] = working
        return working

    # --- importing -------------------------------------------------------------

    def import_file(
        self, project_id: uuid.UUID, *, filename: str, data: bytes
    ) -> ImportResult:
        with self.connect() as conn:
            if repo.get_project(conn, project_id) is None:
                raise UnknownProject(str(project_id))

        source_sha = hashlib.sha256(data).hexdigest()
        path = self._store_bytes(project_id, source_sha, data)

        prior = self.load(project_id)
        prior_identity = prior.identity if prior else None

        # Parse and migrate outside any transaction: the 14 MB files take
        # seconds, and nothing below needs a lock held across them.
        document = import_mspdi(str(path))
        declared = _declared_project_guid(document)
        mismatch = bool(
            prior_identity is not None
            and declared is not None
            and declared != prior_identity.schedule_id
        )
        try:
            schedule, identity, report = migrate(document, identity=prior_identity)
        except MigrationError as error:
            with self.connect() as conn:
                source_id = _record_source(conn, project_id, filename, path, source_sha, data)
                repo.insert_import_batch(
                    conn,
                    project_id=project_id,
                    source_file_id=source_id,
                    status="failed",
                    parser_name=PARSER_NAME,
                    parser_version=PARSER_VERSION,
                    parse_summary={"error": str(error)},
                    error_count=1,
                )
                conn.commit()
            raise

        payload = encode_schedule(schedule)
        digest = canonical_sha256(payload)
        identity_payload = identity.to_dict()

        with self.connect() as conn:
            source_id = _record_source(conn, project_id, filename, path, source_sha, data)
            batch_id = repo.insert_import_batch(
                conn,
                project_id=project_id,
                source_file_id=source_id,
                status="accepted",
                parser_name=PARSER_NAME,
                parser_version=PARSER_VERSION,
                parse_summary={
                    "reconciliation": _counts(report),
                    "declared_project_guid": declared,
                    "project_identity_mismatch": mismatch,
                    "schedule_id": schedule.schedule_id,
                },
            )
            sequence = repo.next_sequence(conn, project_id)
            version_id = repo.insert_version(
                conn,
                project_id=project_id,
                kind="baseline",
                sequence=sequence,
                parent_id=prior.version_id if prior else None,
                canonical_hash=digest,
                schema_version=SCHEMA_VERSION,
                cause_type="import",
                cause_id=batch_id,
                document=payload,
                identity_map=identity_payload,
            )
            repo.set_head(conn, project_id=project_id, kind="baseline", version_id=version_id)
            conn.commit()

        self._resident[project_id] = WorkingSchedule(
            project_id=project_id,
            version_id=version_id,
            sequence=sequence,
            canonical_hash=digest,
            schedule=schedule,
            identity=identity,
        )
        return ImportResult(
            project_id=project_id,
            import_batch_id=batch_id,
            version_id=version_id,
            sequence=sequence,
            canonical_hash=digest,
            source_sha256=source_sha,
            reconciliation=report,
            project_identity_mismatch=mismatch,
            declared_project_guid=declared,
        )

    def _store_bytes(self, project_id: uuid.UUID, sha: str, data: bytes) -> Path:
        folder = self.source_dir / str(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{sha}.xml"
        if not path.exists():
            tmp = path.with_suffix(".xml.part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return path


def _record_source(
    conn: psycopg.Connection,
    project_id: uuid.UUID,
    filename: str,
    path: Path,
    sha: str,
    data: bytes,
) -> uuid.UUID:
    return repo.insert_source_file(
        conn,
        project_id=project_id,
        original_filename=filename,
        file_kind="mspdi_xml",
        storage_uri=path.as_uri(),
        content_hash=sha,
        size_bytes=len(data),
    )


def _verify(project_id: uuid.UUID, row: dict[str, Any]) -> WorkingSchedule:
    schedule = decode_schedule(row["document"])
    recomputed = canonical_sha256(encode_schedule(schedule))
    if recomputed != row["canonical_hash"]:
        raise IntegrityError(
            f"schedule version {row['id']} for project {project_id} is stored under "
            f"{row['canonical_hash']} but its document hashes to {recomputed}"
        )
    return WorkingSchedule(
        project_id=project_id,
        version_id=row["id"],
        sequence=int(row["sequence"]),
        canonical_hash=row["canonical_hash"],
        schedule=schedule,
        identity=IdentityMap.from_dict(row["identity_map"]),
    )


def _declared_project_guid(document: dict[str, Any]) -> str | None:
    project = document.get("project")
    if not isinstance(project, dict):
        return None
    for entry in project.get("external_references", []) or []:
        if isinstance(entry, dict) and entry.get("type") == "GUID" and entry.get("value"):
            return normalise_guid(str(entry["value"]))
    return None


def _counts(report: ReconciliationReport) -> dict[str, int]:
    return {
        "matched": report.matched,
        "new": report.new,
        "rekeyed": report.rekeyed,
        "missing": report.missing,
        "guid_changed": report.guid_changed,
    }
