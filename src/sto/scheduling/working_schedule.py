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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from sto.core.engine import (
    PlanError,
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
    roll_up,
)
from sto.core.engine.result import (
    EXCLUDED,
    SCHEDULED,
    ActivityResult,
    Provenance,
    RelationshipResult,
    ScheduleResult,
    SummaryResult,
    fingerprint_result,
    project_result,
)
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


class ImportRefused(ValueError):
    """A file the importer would not read. Recorded as a failed batch first."""


class IntegrityError(RuntimeError):
    """Stored bytes do not hash to what the row says they hash to.

    Raised for a schedule version whose document disagrees with its canonical
    hash, and for a stored calculation whose rows disagree with the fingerprint
    the header attests to.
    """


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
class CalculationResult:
    """A stored calculation: what it was computed from, and what it produced."""

    project_id: uuid.UUID
    version_id: uuid.UUID
    calculation_id: uuid.UUID
    canonical_hash: str
    fingerprint: str
    scheduled: int
    excluded: int
    summaries: int


@dataclass(frozen=True, slots=True)
class StoredCalculation:
    """A calculation read back from the database and checked against its rows."""

    project_id: uuid.UUID
    version_id: uuid.UUID
    calculation_id: uuid.UUID
    computed_at: datetime
    result: ScheduleResult


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
    #: What the importer warned about while accepting the file.
    warnings: tuple[str, ...] = ()


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

    def load(
        self, project_id: uuid.UUID, *, refresh: bool = False
    ) -> WorkingSchedule | None:
        """The project's verified head, from the resident copy or the database.

        ``refresh`` skips the resident copy and re-reads. Import populates the
        cache from the schedule it has in hand, so without this a caller could
        compute over a document that has never been read back out of
        PostgreSQL, and the hash check this class exists for would not have run
        on the bytes the row actually holds.
        """

        if refresh:
            # Dropped before the read, not after it. Leaving the old entry in
            # place while the new one is verified meant a failed verification
            # raised once and then every ordinary load went on serving the
            # stale schedule -- the opposite of quarantining the project.
            self._resident.pop(project_id, None)
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

    def _record_failure(
        self,
        project_id: uuid.UUID,
        filename: str,
        path: Path,
        source_sha: str,
        data: bytes,
        error: Exception,
    ) -> None:
        """Record a refused import, so the bytes on disk have something naming them."""

        with self.connect() as conn:
            source_id = _record_source(conn, project_id, filename, path, source_sha, data)
            repo.insert_import_batch(
                conn,
                project_id=project_id,
                source_file_id=source_id,
                status="failed",
                parser_name=PARSER_NAME,
                parser_version=PARSER_VERSION,
                parse_summary={"error": str(error), "kind": type(error).__name__},
                error_count=1,
            )
            conn.commit()

    # --- calculating -----------------------------------------------------------

    def calculate(
        self,
        project_id: uuid.UUID,
        *,
        before: timedelta = timedelta(days=90),
        after: timedelta = timedelta(days=365),
    ) -> CalculationResult:
        """Run the engine over a project's stored head and store the answer.

        The horizon is the caller's, not the file's, so it is a parameter and
        it is recorded on the row: the same document over a wider window is a
        different calculation, and a stored result that did not say which
        could not be read back a month later.

        The document is re-read from PostgreSQL and its hash re-derived from
        what came back, so a calculation is never computed over bytes that do
        not hash to what they claim -- not even straight after the import that
        put them there, whose in-memory copy the resident cache holds.
        """

        working = self.load(project_id, refresh=True)
        if working is None:
            raise UnknownProject(str(project_id))
        schedule = working.schedule
        start = schedule.project.start
        if start is None:
            raise PlanError(
                "PROJECT_START_MISSING",
                None,
                "the stored schedule declares no start, so there is nothing to compile around",
            )
        horizon = (start - before, start + after)
        plan = build_plan(schedule, horizon)
        forward = forward_pass(
            plan.network,
            snap_milestones=plan.snap_milestones,
            progress_policy=plan.progress_policy,
        )
        backward = backward_pass(
            plan.network,
            forward,
            snap_milestones=plan.snap_milestones,
        )
        floats = float_analysis(
            plan.network, forward, backward, threshold=plan.critical_float_threshold
        )
        rollup = roll_up(
            plan.wbs_children,
            {uid: (row.early_start, row.early_finish) for uid, row in forward.by_uid().items()},
        )
        result = project_result(
            plan,
            forward,
            backward,
            floats,
            rollup,
            canonical_hash=working.canonical_hash,
            horizon=horizon,
        )
        with self.connect() as conn:
            calculation_id = repo.insert_calculation(
                conn,
                project_id=project_id,
                version_id=working.version_id,
                result=result,
            )
            conn.commit()
        scheduled = sum(1 for row in result.activities if row.disposition == SCHEDULED)
        return CalculationResult(
            project_id=project_id,
            version_id=working.version_id,
            calculation_id=calculation_id,
            canonical_hash=working.canonical_hash,
            fingerprint=result.fingerprint,
            scheduled=scheduled,
            excluded=len(result.activities) - scheduled,
            summaries=len(result.summaries),
        )


    def read_calculation(
        self, project_id: uuid.UUID, *, calculation_id: uuid.UUID | None = None
    ) -> StoredCalculation | None:
        """A stored calculation, rebuilt from its rows and checked against them.

        A schedule version is protected by re-deriving its hash from the stored
        document on every load. A calculation needs the same protection and
        cannot borrow it: its header carries a fingerprint over rows that live
        in two other tables, so a row edited after the insert would be served
        as an answer while the fingerprint still attested to the original.

        So the header and both row sets are read together, the result is
        reassembled, and its fingerprint is recomputed. A mismatch is an
        :class:`IntegrityError`, not a set of dates.
        """

        with self.connect() as conn:
            if repo.get_project(conn, project_id) is None:
                raise UnknownProject(str(project_id))
            if calculation_id is None:
                head = repo.head_version(
                    conn, project_id=project_id, kind="baseline", with_document=False
                )
                if head is None:
                    return None
                header = repo.get_latest_calculation(conn, version_id=head["id"])
            else:
                header = repo.get_calculation(conn, calculation_id=calculation_id)
                if header is not None and header["project_id"] != project_id:
                    # Addressed by identifier, but read on behalf of a project.
                    # Returning another project's calculation under this
                    # project's identifier would misattribute it as well as
                    # disclose it.
                    raise UnknownProject(
                        f"calculation {calculation_id} does not belong to project {project_id}"
                    )
            if header is None:
                return None
            rows = repo.get_activity_results(conn, calculation_id=header["id"])
            spans = repo.get_summary_results(conn, calculation_id=header["id"])
            version = repo.get_version(
                conn, version_id=header["version_id"], with_document=True
            )
        if version is None:
            raise IntegrityError(
                f"calculation {header['id']} names version {header['version_id']}, "
                "which is not in the database"
            )
        # The calculation's own fingerprint says nothing about the document it
        # was computed from -- so a version_id repointed after the insert, or a
        # stored document altered under it, left the result verifiable and its
        # input not. The named version is verified here, and it has to be this
        # project's and the one the header says it hashed.
        named = _verify(version["project_id"], version)
        if named.project_id != project_id:
            raise IntegrityError(
                f"calculation {header['id']} for project {project_id} names version "
                f"{named.version_id}, which belongs to project {named.project_id}"
            )
        if named.canonical_hash != header["canonical_hash"]:
            raise IntegrityError(
                f"calculation {header['id']} says it was computed from "
                f"{header['canonical_hash']}, but version {named.version_id} holds "
                f"{named.canonical_hash}"
            )

        result = _rebuild_result(header, rows, spans)
        recomputed = fingerprint_result(result)
        if recomputed != header["result_fingerprint"]:
            raise IntegrityError(
                f"calculation {header['id']} for project {project_id} is stored under "
                f"{header['result_fingerprint']} but its rows fingerprint to {recomputed}"
            )
        return StoredCalculation(
            project_id=project_id,
            version_id=header["version_id"],
            calculation_id=header["id"],
            computed_at=header["computed_at"],
            result=replace(result, fingerprint=recomputed),
        )

    def latest_calculation(self, project_id: uuid.UUID) -> dict[str, Any] | None:
        """The stored calculation for a project's head, with the source dates beside it.

        Read through :meth:`read_calculation`, so the rows served here are the
        rows the header's fingerprint attests to. Serving them from the tables
        directly would put edited or corrupted dates in front of a reader under
        a hash that still vouched for the originals.

        The imported dates come from the document, not from a second copy: a
        row that stored what the file said would be a third place for it to
        drift from. They are read off the schedule the calculation names.
        """

        working = self.load(project_id)
        if working is None:
            raise UnknownProject(str(project_id))
        stored = self.read_calculation(project_id)
        if stored is None:
            return None

        result = stored.result
        provenance = result.provenance
        schedule = working.schedule
        activities = {activity.uid: activity for activity in schedule.activities}
        nodes = {node.uid: node for node in schedule.wbs_nodes}

        activity_rows = []
        for row in result.activities:
            activity = activities.get(row.uid)
            observed = activity.source_observations if activity is not None else None
            source_start = None if observed is None else observed.start
            source_finish = None if observed is None else observed.finish
            agrees = None
            if row.early_start is not None and source_start is not None:
                agrees = row.early_start == source_start and row.early_finish == source_finish
            activity_rows.append(
                {
                    "activity_uid": row.uid,
                    "code": None if activity is None else activity.code,
                    "name": None if activity is None else activity.name,
                    "disposition": row.disposition,
                    "source_start": source_start,
                    "source_finish": source_finish,
                    "early_start": row.early_start,
                    "early_finish": row.early_finish,
                    "late_start": row.late_start,
                    "late_finish": row.late_finish,
                    "remaining_start": row.remaining_start,
                    "total_float_seconds": row.total_float,
                    "free_float_seconds": row.free_float,
                    "critical": row.critical,
                    "progress_state": row.state,
                    "placed_by": row.placed_by,
                    "exclusion_code": row.exclusion_code,
                    "assumptions": list(row.assumptions),
                    "agrees_with_source": agrees,
                }
            )
        activity_rows.sort(key=lambda row: str(row["activity_uid"]))

        def _summary(uid, start, finish, placed):
            node = nodes.get(uid)
            observed = node.source_observations if node is not None else None
            return {
                "wbs_uid": uid,
                "code": None if node is None else node.code,
                "name": None if node is None else node.name,
                "span_start": start,
                "span_finish": finish,
                "placed": placed,
                "source_start": None if observed is None else observed.start,
                "source_finish": None if observed is None else observed.finish,
            }

        summary_rows = [
            _summary(row.uid, row.start, row.finish, row.placed) for row in result.summaries
        ]
        # A branch with nothing beneath it is shown as a branch with no span,
        # so "not calculated" and "not in the file" stay different answers.
        summary_rows += [_summary(uid, None, None, 0) for uid in result.empty_summaries]
        summary_rows.sort(key=lambda row: str(row["wbs_uid"]))

        agreed = sum(1 for row in activity_rows if row["agrees_with_source"] is True)
        compared = sum(1 for row in activity_rows if row["agrees_with_source"] is not None)
        return {
            "project_id": project_id,
            "version_id": stored.version_id,
            "calculation_id": stored.calculation_id,
            "canonical_hash": provenance.canonical_hash,
            "fingerprint": result.fingerprint,
            "horizon_start": provenance.horizon_start,
            "horizon_finish": provenance.horizon_finish,
            "progress_policy": provenance.progress_policy,
            "critical_float_threshold": provenance.critical_float_threshold,
            "status_time": provenance.status_time,
            "status_time_outside_window": provenance.status_time_outside_window,
            "profiles": {
                "forward": provenance.forward_profile,
                "backward": provenance.backward_profile,
                "criticality": provenance.criticality_profile,
                "rollup": provenance.rollup_profile,
                "progress": provenance.progress_profile,
                "result": provenance.result_profile,
            },
            "computed_at": stored.computed_at,
            "counts": {
                "activities": len(activity_rows),
                "scheduled": sum(
                    1 for row in activity_rows if row["disposition"] == SCHEDULED
                ),
                "summaries": len(summary_rows),
                "compared_with_source": compared,
                "agreeing_with_source": agreed,
            },
            "relationships": [
                {
                    "relationship_uid": edge.uid,
                    "disposition": edge.disposition,
                    "code": edge.code,
                    "detail": edge.detail,
                }
                for edge in result.relationships
            ],
            "activities": activity_rows,
            "summaries": summary_rows,
        }

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
        #
        # A parse failure is recorded exactly as a migration failure is. Before
        # this it was raised from outside the handler below, so malformed input
        # produced an uncaught server error, no failed batch, and raw bytes on
        # disk that nothing referred to.
        try:
            document = import_mspdi(str(path))
        except Exception as error:  # noqa: BLE001 - recorded, not hidden
            self._record_failure(project_id, filename, path, source_sha, data, error)
            raise ImportRefused(str(error)) from error
        warnings = tuple(
            str(item) for item in document.get("import_validation", {}).get("warnings", [])
        )
        declared = _declared_project_guid(document)
        mismatch = bool(
            prior_identity is not None
            and declared is not None
            and declared != prior_identity.schedule_id
        )
        try:
            schedule, identity, report = migrate(document, identity=prior_identity)
        except MigrationError as error:
            self._record_failure(project_id, filename, path, source_sha, data, error)
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
                    # What the importer said about the file it accepted. An
                    # accepted import with warnings is not the same thing as a
                    # clean one, and the batch recorded zero either way.
                    "warnings": list(warnings),
                },
                warning_count=len(warnings),
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
            warnings=warnings,
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


def _rebuild_result(
    header: dict[str, Any], rows: list[dict[str, Any]], spans: list[dict[str, Any]]
) -> ScheduleResult:
    """Reassemble a stored calculation exactly as the engine produced it.

    Every profile is read from the stored header rather than defaulted, because
    the point of reading it back is to detect a row that no longer matches its
    fingerprint, and a default that quietly agreed with the current code would
    hide exactly the case where the rules changed underneath a stored answer.
    """

    profiles = header["profiles"]
    provenance = Provenance(
        canonical_hash=header["canonical_hash"],
        epoch=header["epoch"],
        horizon_start=header["horizon_start"],
        horizon_finish=header["horizon_finish"],
        progress_policy=header["progress_policy"],
        critical_float_threshold=int(header["critical_float_threshold"]),
        status_time=header["status_time"],
        status_time_outside_window=header["status_time_outside_window"],
        forward_profile=profiles["forward"],
        backward_profile=profiles["backward"],
        criticality_profile=profiles["criticality"],
        rollup_profile=profiles["rollup"],
        progress_profile=profiles["progress"],
        result_profile=profiles["result"],
    )
    activities = tuple(
        ActivityResult(
            uid=row["activity_uid"],
            disposition=row["disposition"],
            early_start=row["early_start"],
            early_finish=row["early_finish"],
            late_start=row["late_start"],
            late_finish=row["late_finish"],
            remaining_start=row["remaining_start"],
            total_float=(
                None if row["total_float_seconds"] is None else int(row["total_float_seconds"])
            ),
            free_float=(
                None if row["free_float_seconds"] is None else int(row["free_float_seconds"])
            ),
            start_float=(
                None if row["start_float_seconds"] is None else int(row["start_float_seconds"])
            ),
            finish_float=(
                None if row["finish_float_seconds"] is None else int(row["finish_float_seconds"])
            ),
            critical=row["critical"],
            state=row["progress_state"],
            placed_by=row["placed_by"],
            driving_relationship_uid=row["driving_relationship_uid"],
            late_placed_by=row["late_placed_by"],
            late_driving_relationship_uid=row["late_driving_relationship_uid"],
            constraint_override=row["constraint_override"],
            exclusion_code=row["exclusion_code"],
            assumptions=tuple(row["assumptions"]),
        )
        for row in rows
    )
    summaries = tuple(
        SummaryResult(
            uid=span["wbs_uid"],
            start=span["span_start"],
            finish=span["span_finish"],
            placed=int(span["placed"]),
        )
        for span in spans
        if span["span_start"] is not None
    )
    empty = tuple(span["wbs_uid"] for span in spans if span["span_start"] is None)
    relationships = tuple(
        RelationshipResult(
            uid=uuid.UUID(edge["uid"]),
            disposition=edge["disposition"],
            code=edge["code"],
            detail=edge["detail"],
        )
        for edge in header["relationship_dispositions"]
    )
    return ScheduleResult(
        provenance=provenance,
        activities=activities,
        summaries=summaries,
        relationships=relationships,
        empty_summaries=empty,
    )


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
    try:
        schedule = decode_schedule(row["document"])
        identity = IdentityMap.from_dict(row["identity_map"])
    except Exception as error:  # noqa: BLE001 - contained, not hidden
        # A stored document or identity map this code cannot read is exactly as
        # much a failure of *this* project as a hash that does not match, and
        # exactly as little a reason to refuse every other project at boot.
        # Before this it escaped the integrity contract and aborted the whole
        # rebuild: removing a schema_version from one row took every project
        # with it.
        raise IntegrityError(
            f"schedule version {row['id']} for project {project_id} cannot be read: {error}"
        ) from error
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
        identity=identity,
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
        "guid_duplicated_in_snapshot": report.guid_duplicated_in_snapshot,
    }
