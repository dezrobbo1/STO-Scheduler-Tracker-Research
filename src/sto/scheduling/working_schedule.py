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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
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
from sto.core.model.enums import ActivityKind
from sto.core.model.ids import normalise_guid
from sto.core.model.migrate.sto_v011 import MigrationError, migrate
from sto.legacy import import_mspdi
from sto.persistence import repositories as repo

PARSER_NAME = "sto.legacy.import_mspdi"
PARSER_VERSION = "0.1.1"


def _profiles(provenance: Provenance) -> dict[str, str]:
    return {
        "forward": provenance.forward_profile,
        "backward": provenance.backward_profile,
        "criticality": provenance.criticality_profile,
        "rollup": provenance.rollup_profile,
        "progress": provenance.progress_profile,
        "result": provenance.result_profile,
    }


def _result_context(result: ScheduleResult) -> tuple[Any, ...]:
    provenance = result.provenance
    return (
        provenance.epoch,
        provenance.horizon_start,
        provenance.horizon_finish,
        provenance.progress_policy,
        provenance.critical_float_threshold,
        provenance.status_time,
        provenance.status_time_outside_window,
        provenance.resource_calendars_apply,
        tuple(sorted(_profiles(provenance).items())),
    )


def _stored_context(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["epoch"],
        row["horizon_start"],
        row["horizon_finish"],
        row["progress_policy"],
        int(row["critical_float_threshold"]),
        row["status_time"],
        row["status_time_outside_window"],
        row["resource_calendars_apply"],
        tuple(sorted(row["profiles"].items())),
    )


def _projected_context(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["epoch"],
        row["horizon_start"],
        row["horizon_finish"],
        row["progress_policy"],
        row["critical_float_threshold"],
        row["status_time"],
        row["status_time_outside_window"],
        row["resource_calendars_apply"],
        tuple(sorted(row["profiles"].items())),
    )


def _relationship_context_codes(
    schedule: Schedule,
    edges: Iterable[tuple[uuid.UUID, str]],
) -> dict[uuid.UUID, tuple[str, ...]]:
    """Map every exceptional relationship result back to both endpoint rows.

    ``ScheduleResult.relationships`` contains exactly the edges that were not
    ordinary measured precedence: assumed, excluded, or released by progress.
    PL14 changes a duration and then interprets both the edited row and the
    downstream movement, so an exceptional edge incident to the selected row is
    part of that scenario's scheduling context even when the activity row itself
    carries no activity-level assumption.
    """

    relationships = {row.uid: row for row in schedule.relationships}
    by_activity: dict[uuid.UUID, set[str]] = {}
    for relationship_uid, code in edges:
        relationship = relationships.get(relationship_uid)
        if relationship is None:
            raise IntegrityError(
                f"calculation relationship {relationship_uid} is not present in its schedule"
            )
        for activity_uid in (
            relationship.predecessor_uid,
            relationship.successor_uid,
        ):
            by_activity.setdefault(activity_uid, set()).add(code)
    return {
        activity_uid: tuple(sorted(codes))
        for activity_uid, codes in by_activity.items()
    }


def _with_relationship_context(
    schedule: Schedule,
    projected: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Expose exceptional edge context on the endpoint rows the planner shows."""

    if projected is None:
        return None
    context = _relationship_context_codes(
        schedule,
        (
            (edge["relationship_uid"], edge["code"])
            for edge in projected["relationships"]
        ),
    )
    if not context:
        return projected
    rows: list[dict[str, Any]] = []
    for row in projected["activities"]:
        extra = context.get(row["activity_uid"], ())
        if not extra:
            rows.append(row)
            continue
        updated = dict(row)
        updated["assumptions"] = sorted(set((*row["assumptions"], *extra)))
        rows.append(updated)
    decorated = dict(projected)
    decorated["activities"] = rows
    return decorated


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


class NoSchedule(LookupError):
    """The project exists and has had no import, so there is nothing to compute.

    Distinct from :class:`UnknownProject` because a caller told "no such
    project" about one it can see in the list is told something false.
    """


class StaleSchedule(RuntimeError):
    """The project head changed while an operation was being prepared."""


class ScenarioRejected(ValueError):
    """A controlled refusal to create a planner scenario."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


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
    #: Every WBS row the calculation stored, a branch with nothing beneath it
    #: included. It is stored as a row with no span, so counting only the ones
    #: with spans made this endpoint disagree with the one that reads it back.
    summaries: int
    #: Whether this run was already stored. A calculation is deterministic, so
    #: asking for the same one twice is not an error and does not make a second
    #: row; the caller is told which it got.
    already_stored: bool = False


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    project_id: uuid.UUID
    baseline_version_id: uuid.UUID
    scenario_version_id: uuid.UUID
    sequence: int
    canonical_hash: str
    calculation_id: uuid.UUID
    fingerprint: str
    activity_uid: uuid.UUID
    before_seconds: int
    after_seconds: int


@dataclass(frozen=True, slots=True)
class ScenarioResetResult:
    """The exact baseline and calculation made active by a reset."""

    project_id: uuid.UUID
    baseline_version_id: uuid.UUID
    calculation_id: uuid.UUID | None
    fingerprint: str | None


@dataclass(frozen=True, slots=True)
class StoredCalculation:
    """A calculation read back from the database and checked against its rows."""

    project_id: uuid.UUID
    version_id: uuid.UUID
    calculation_id: uuid.UUID
    computed_at: datetime
    result: ScheduleResult
    #: The document the calculation names, verified on the way out. Anything
    #: reading source values beside these dates must read them from *this*,
    #: not from whatever the project's head happens to be now.
    schedule: Schedule | None = None


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
    _state_lock: RLock = field(default_factory=RLock, repr=False)

    # --- reading ---------------------------------------------------------------

    def rebuild(self) -> int:
        """Load and verify every project's baseline head. Called at boot.

        A version that does not hash to what it says is not served and is
        not fatal to the process: the other projects are fine, and a boot
        that refused entirely would hide which one is not. It is reported by
        ``/api/health`` and by that project's own routes.
        """

        with self._state_lock:
            self._resident.clear()
            self.integrity_failures.clear()
        with self.connect() as conn:
            heads = repo.heads_for_all_projects(conn)
        for head in heads:
            if head["head_kind"] != "baseline":
                continue
            try:
                self.load(head["project_id"])
            except IntegrityError:
                # ``load`` publishes the diagnosis only when the failed row is
                # still the head. Repeating it here would undo that check.
                pass
        return len(self._resident)

    def resident_ids(self) -> frozenset[uuid.UUID]:
        with self._state_lock:
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

        with self._state_lock:
            cached = None if refresh else self._resident.get(project_id)
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
            # Verification happened outside the cache. An import can commit
            # and publish a newer resident head while this older row is being
            # checked, so only evict and diagnose the version that actually
            # failed. If the database head moved before the resident was
            # installed, the second head read closes that smaller window.
            with self._state_lock:
                resident = self._resident.get(project_id)
                if resident is None or resident.version_id == row["id"]:
                    with self.connect() as conn:
                        current = repo.head_version(
                            conn,
                            project_id=project_id,
                            kind="baseline",
                            with_document=False,
                        )
                    if current is not None and current["id"] == row["id"]:
                        if resident is not None:
                            self._resident.pop(project_id, None)
                        self.integrity_failures[project_id] = str(error)
            raise
        # A refresh is a verified point-in-time read for calculation. It must
        # not replace the resident head: an import can commit and install a
        # newer resident version while this database read is being verified.
        with self._state_lock:
            self.integrity_failures.pop(project_id, None)
            if not refresh:
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

    @staticmethod
    def _calculate_working(
        working: WorkingSchedule,
        *,
        before: timedelta,
        after: timedelta,
    ) -> ScheduleResult:
        """Run the one production engine over one verified immutable version."""

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
            {
                uid: (row.early_start, row.early_finish)
                for uid, row in forward.by_uid().items()
            },
        )
        return project_result(
            plan,
            forward,
            backward,
            floats,
            rollup,
            canonical_hash=working.canonical_hash,
            horizon=horizon,
        )

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
            raise NoSchedule(str(project_id))
        result = self._calculate_working(working, before=before, after=after)
        already_stored = False
        with self.connect() as conn:
            if not repo.lock_project(conn, project_id):
                raise UnknownProject(str(project_id))
            current_version = repo.lock_head_version_id(
                conn, project_id=project_id, kind="baseline"
            )
            if current_version != working.version_id:
                raise StaleSchedule(
                    f"baseline moved from {working.version_id} to {current_version} "
                    "while the calculation was running; calculate the current version"
                )
            # Attempted, not looked up first. The same document over the same
            # window under the same rules is the same answer and the table
            # stores it once; two callers asking at the same moment both pass a
            # lookup, and one insert then loses to the constraint. This yields
            # to the winner instead of colliding with it.
            calculation_id = repo.insert_calculation(
                conn,
                project_id=project_id,
                version_id=working.version_id,
                result=result,
            )
            if calculation_id is None:
                existing = repo.find_calculation(
                    conn, version_id=working.version_id, fingerprint=result.fingerprint
                )
                assert existing is not None
                calculation_id = existing["id"]
                already_stored = True
            scenario_id = repo.lock_head_version_id(
                conn, project_id=project_id, kind="scenario"
            )
            if scenario_id is not None:
                scenario_calculation = repo.get_latest_calculation(
                    conn, version_id=scenario_id
                )
                if (
                    scenario_calculation is None
                    or _stored_context(scenario_calculation) != _result_context(result)
                ):
                    # The scenario remains immutable history, but it can no
                    # longer be displayed as a duration-only comparison with
                    # this baseline calculation.
                    repo.delete_head(conn, project_id=project_id, kind="scenario")
            conn.commit()
        if already_stored:
            # Reusing a stored calculation is serving it, so it goes through the
            # same fingerprint check as any other read. Reporting success for
            # rows altered under it would tell the caller their answer was
            # stored when it is no longer the answer.
            self.read_calculation(project_id, calculation_id=calculation_id)
        scheduled = sum(1 for row in result.activities if row.disposition == SCHEDULED)
        return CalculationResult(
            already_stored=already_stored,
            project_id=project_id,
            version_id=working.version_id,
            calculation_id=calculation_id,
            canonical_hash=working.canonical_hash,
            fingerprint=result.fingerprint,
            scheduled=scheduled,
            excluded=len(result.activities) - scheduled,
            summaries=len(result.summaries) + len(result.empty_summaries),
        )

    def create_duration_scenario(
        self,
        project_id: uuid.UUID,
        *,
        expected_version_id: uuid.UUID,
        activity_uid: uuid.UUID,
        planned_duration_seconds: int,
        before: timedelta | None = None,
        after: timedelta | None = None,
    ) -> ScenarioResult:
        """Derive, calculate and atomically publish one duration scenario.

        The imported baseline document is never updated. A scenario is a
        comparison with one exact stored baseline calculation, so it reuses
        that calculation's window and engine/policy context rather than the
        method's current defaults. Expensive engine work happens before the
        transaction, then both the active version and the baseline calculation
        are checked again under the project lock. A stale edit therefore stores
        neither a version nor a calculation.
        """

        if planned_duration_seconds <= 0:
            raise ScenarioRejected(
                "DURATION_INVALID", "planned duration must be a positive number of seconds"
            )

        baseline = self.load(project_id, refresh=True)
        if baseline is None:
            raise NoSchedule(str(project_id))
        baseline_calculation = self.read_calculation(project_id, kind="baseline")
        if baseline_calculation is None:
            raise ScenarioRejected(
                "BASELINE_CALCULATION_REQUIRED",
                "calculate the imported baseline before creating a scenario",
            )

        with self.connect() as conn:
            scenario_head = repo.head_version(
                conn, project_id=project_id, kind="scenario", with_document=False
            )
        active_version_id = (
            scenario_head["id"] if scenario_head is not None else baseline.version_id
        )
        if active_version_id != expected_version_id:
            raise StaleSchedule(
                f"planner state moved from {expected_version_id} to {active_version_id}; "
                "reload before applying the edit"
            )

        activities = baseline.schedule.activity_by_uid()
        activity = activities.get(activity_uid)
        if activity is None:
            raise ScenarioRejected("ACTIVITY_NOT_FOUND", "the selected activity does not exist")
        if activity.kind is not ActivityKind.TASK:
            raise ScenarioRejected(
                "ACTIVITY_NOT_LEAF_TASK", "only a schedulable leaf activity can be edited"
            )
        if not activity.active:
            raise ScenarioRejected("ACTIVITY_INACTIVE", "the selected activity is inactive")
        if activity.manual:
            raise ScenarioRejected(
                "ACTIVITY_MANUALLY_SCHEDULED",
                "the selected activity is manually scheduled",
            )
        if activity.actual_start is not None or activity.actual_finish is not None:
            raise ScenarioRejected(
                "ACTIVITY_HAS_PROGRESS",
                "PL14 edits only not-started activities with no actual dates",
            )
        if activity.planned_duration is None or activity.planned_duration.seconds <= 0:
            raise ScenarioRejected(
                "ACTIVITY_DURATION_UNAVAILABLE",
                "the selected activity has no positive planned duration",
            )
        if (
            activity.remaining_duration is not None
            and activity.remaining_duration.seconds == 0
        ):
            raise ScenarioRejected(
                "ACTIVITY_REMAINING_DURATION_ZERO",
                "PL14 cannot edit an activity whose imported remaining duration is zero",
            )

        baseline_rows = baseline_calculation.result.by_uid()
        baseline_row = baseline_rows.get(activity_uid)
        if baseline_row is None or baseline_row.disposition != SCHEDULED:
            code = None if baseline_row is None else baseline_row.exclusion_code
            raise ScenarioRejected(
                "ACTIVITY_NOT_SUPPORTED",
                "the selected activity is not calculated"
                + (" (" + code + ")" if code else ""),
            )
        relationship_context = _relationship_context_codes(
            baseline.schedule,
            (
                (edge.uid, edge.code)
                for edge in baseline_calculation.result.relationships
            ),
        )
        scenario_assumptions = tuple(
            sorted(
                set(
                    (
                        *baseline_row.assumptions,
                        *relationship_context.get(activity_uid, ()),
                    )
                )
            )
        )
        if scenario_assumptions:
            raise ScenarioRejected(
                "ACTIVITY_HAS_ASSUMPTIONS",
                "choose an activity calculated without assumptions; this one uses "
                + ", ".join(scenario_assumptions),
            )

        old_seconds = activity.planned_duration.seconds
        if old_seconds == planned_duration_seconds:
            raise ScenarioRejected(
                "DURATION_UNCHANGED", "the new planned duration equals the baseline duration"
            )
        changed = replace(
            activity,
            planned_duration=replace(
                activity.planned_duration, seconds=planned_duration_seconds
            ),
            remaining_duration=(
                None
                if activity.remaining_duration is None
                else replace(
                    activity.remaining_duration, seconds=planned_duration_seconds
                )
            ),
        )
        schedule = replace(
            baseline.schedule,
            activities=tuple(
                changed if row.uid == activity_uid else row
                for row in baseline.schedule.activities
            ),
        )
        payload = encode_schedule(schedule)
        digest = canonical_sha256(payload)
        candidate = WorkingSchedule(
            project_id=project_id,
            version_id=uuid.uuid4(),
            sequence=0,
            canonical_hash=digest,
            schedule=schedule,
            identity=baseline.identity,
        )

        project_start = baseline.schedule.project.start
        if project_start is None:
            raise ScenarioRejected(
                "BASELINE_CALCULATION_CONTEXT_UNAVAILABLE",
                "the calculated baseline has no project start from which to reproduce its window",
            )
        baseline_provenance = baseline_calculation.result.provenance
        baseline_before = project_start - baseline_provenance.horizon_start
        baseline_after = baseline_provenance.horizon_finish - project_start
        if before is not None and before != baseline_before:
            raise ScenarioRejected(
                "SCENARIO_CONTEXT_MUST_MATCH_BASELINE",
                "a planner scenario must use the active baseline calculation window",
            )
        if after is not None and after != baseline_after:
            raise ScenarioRejected(
                "SCENARIO_CONTEXT_MUST_MATCH_BASELINE",
                "a planner scenario must use the active baseline calculation window",
            )
        result = self._calculate_working(
            candidate, before=baseline_before, after=baseline_after
        )
        if _result_context(result) != _result_context(baseline_calculation.result):
            raise ScenarioRejected(
                "BASELINE_CALCULATION_CONTEXT_INCOMPATIBLE",
                "the active baseline was calculated under a different engine or policy context; "
                "recalculate the baseline before creating a scenario",
            )

        change_id = uuid.uuid4()
        with self.connect() as conn:
            if not repo.lock_project(conn, project_id):
                raise UnknownProject(str(project_id))
            current_baseline = repo.head_version(
                conn, project_id=project_id, kind="baseline", with_document=False
            )
            current_scenario_id = repo.lock_head_version_id(
                conn, project_id=project_id, kind="scenario"
            )
            current_active_id = (
                current_scenario_id
                if current_scenario_id is not None
                else None if current_baseline is None else current_baseline["id"]
            )
            current_baseline_calculation = (
                None
                if current_baseline is None
                else repo.get_latest_calculation(
                    conn, version_id=current_baseline["id"]
                )
            )
            if (
                current_baseline is None
                or current_baseline["id"] != baseline.version_id
                or current_active_id != expected_version_id
            ):
                raise StaleSchedule(
                    f"planner state moved from {expected_version_id} to "
                    f"{current_active_id}; reload before applying the edit"
                )
            if (
                current_baseline_calculation is None
                or current_baseline_calculation["id"]
                != baseline_calculation.calculation_id
            ):
                current_calculation_id = (
                    None
                    if current_baseline_calculation is None
                    else current_baseline_calculation["id"]
                )
                raise StaleSchedule(
                    "baseline calculation moved from "
                    f"{baseline_calculation.calculation_id} to {current_calculation_id}; "
                    "reload before applying the edit"
                )
            sequence = repo.next_sequence(conn, project_id)
            scenario_version_id = repo.insert_version(
                conn,
                project_id=project_id,
                kind="scenario",
                sequence=sequence,
                parent_id=baseline.version_id,
                canonical_hash=digest,
                schema_version=SCHEMA_VERSION,
                cause_type="planner_edit",
                cause_id=change_id,
                document=payload,
                identity_map=baseline.identity.to_dict(),
            )
            repo.insert_scenario_change(
                conn,
                change_id=change_id,
                project_id=project_id,
                baseline_version_id=baseline.version_id,
                scenario_version_id=scenario_version_id,
                activity_uid=activity_uid,
                before_seconds=old_seconds,
                after_seconds=planned_duration_seconds,
                remaining_before_seconds=(
                    None
                    if activity.remaining_duration is None
                    else activity.remaining_duration.seconds
                ),
                remaining_after_seconds=(
                    None
                    if activity.remaining_duration is None
                    else planned_duration_seconds
                ),
            )
            calculation_id = repo.insert_calculation(
                conn,
                project_id=project_id,
                version_id=scenario_version_id,
                result=result,
            )
            assert calculation_id is not None
            repo.set_head(
                conn,
                project_id=project_id,
                kind="scenario",
                version_id=scenario_version_id,
            )
            conn.commit()

        return ScenarioResult(
            project_id=project_id,
            baseline_version_id=baseline.version_id,
            scenario_version_id=scenario_version_id,
            sequence=sequence,
            canonical_hash=digest,
            calculation_id=calculation_id,
            fingerprint=result.fingerprint,
            activity_uid=activity_uid,
            before_seconds=old_seconds,
            after_seconds=planned_duration_seconds,
        )

    def reset_scenario(
        self, project_id: uuid.UUID, *, expected_version_id: uuid.UUID
    ) -> ScenarioResetResult:
        """Move the active planner state back to the current baseline."""

        with self.connect() as conn:
            if not repo.lock_project(conn, project_id):
                raise UnknownProject(str(project_id))
            baseline = repo.head_version(
                conn, project_id=project_id, kind="baseline", with_document=False
            )
            if baseline is None:
                raise NoSchedule(str(project_id))
            scenario_id = repo.lock_head_version_id(
                conn, project_id=project_id, kind="scenario"
            )
            active_id = scenario_id if scenario_id is not None else baseline["id"]
            if active_id != expected_version_id:
                raise StaleSchedule(
                    f"planner state moved from {expected_version_id} to {active_id}; "
                    "reload before resetting"
                )
            if scenario_id is not None:
                repo.delete_head(conn, project_id=project_id, kind="scenario")
            calculation = repo.get_latest_calculation(conn, version_id=baseline["id"])
            conn.commit()
        return ScenarioResetResult(
            project_id=project_id,
            baseline_version_id=baseline["id"],
            calculation_id=None if calculation is None else calculation["id"],
            fingerprint=(
                None if calculation is None else calculation["result_fingerprint"]
            ),
        )

    def read_calculation(
        self,
        project_id: uuid.UUID,
        *,
        calculation_id: uuid.UUID | None = None,
        kind: str = "baseline",
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
                    conn, project_id=project_id, kind=kind, with_document=False
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
        # V003 keeps the calculation's version association immutable, including
        # across imports with identical document hashes. Verify the named
        # document here as well: its contents must still be this project's
        # and the ones the calculation header says it hashed.
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
            schedule=named.schedule,
        )

    def latest_calculation(
        self,
        project_id: uuid.UUID,
        *,
        kind: str = "baseline",
        version_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """The stored calculation for a project's head, with the source dates beside it.

        Read through :meth:`read_calculation`, so the rows served here are the
        rows the header's fingerprint attests to. Serving them from the tables
        directly would put edited or corrupted dates in front of a reader under
        a hash that still vouched for the originals.

        The imported dates come from the document, not from a second copy: a
        row that stored what the file said would be a third place for it to
        drift from. They are read off the schedule the calculation names.
        """

        if version_id is None:
            stored = self.read_calculation(project_id, kind=kind)
        else:
            with self.connect() as conn:
                header = repo.get_latest_calculation(conn, version_id=version_id)
            stored = (
                None
                if header is None
                else self.read_calculation(
                    project_id, calculation_id=header["id"], kind=kind
                )
            )
        if stored is None:
            return None

        result = stored.result
        provenance = result.provenance
        # The calculation's own document, not the project's current head. The
        # head can move between the two reads -- a concurrent import is enough
        # -- and looking one version's row identifiers up in another version's
        # schedule puts stale names and stale imported dates beside a
        # fingerprint-verified result, which is a false comparison, not a
        # stale one.
        schedule = stored.schedule
        assert schedule is not None
        activities = {activity.uid: activity for activity in schedule.activities}
        nodes = {node.uid: node for node in schedule.wbs_nodes}

        activity_rows = []
        for row in result.activities:
            activity = activities.get(row.uid)
            observed = activity.source_observations if activity is not None else None
            source_start = None if observed is None else observed.start
            source_finish = None if observed is None else observed.finish
            agrees = None
            if (
                row.early_start is not None
                and source_start is not None
                and source_finish is not None
            ):
                # Both source dates, or no verdict. Comparing a computed finish
                # with an absent one made the row say the engine disagrees with
                # the file about a value the file never gave.
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
                    "late_placed_by": row.late_placed_by,
                    "constraint_override": row.constraint_override,
                    "exclusion_code": row.exclusion_code,
                    "exclusion_detail": row.exclusion_detail,
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
            "epoch": provenance.epoch,
            "horizon_start": provenance.horizon_start,
            "horizon_finish": provenance.horizon_finish,
            "progress_policy": provenance.progress_policy,
            "critical_float_threshold": provenance.critical_float_threshold,
            "status_time": provenance.status_time,
            "status_time_outside_window": provenance.status_time_outside_window,
            "resource_calendars_apply": provenance.resource_calendars_apply,
            "profiles": _profiles(provenance),
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

    def planner_state(self, project_id: uuid.UUID) -> dict[str, Any]:
        """The active baseline/scenario pair used by the planner page."""

        with self.connect() as conn:
            # Every operation that moves a head takes this project-row lock.
            # Keep it while reading both heads so READ COMMITTED cannot pair a
            # baseline from before a concurrent import with a scenario from
            # after it.
            if not repo.lock_project(conn, project_id):
                raise UnknownProject(str(project_id))
            project = repo.get_project(conn, project_id)
            assert project is not None
            baseline_head = repo.head_version(
                conn, project_id=project_id, kind="baseline", with_document=True
            )
            scenario_head = repo.head_version(
                conn, project_id=project_id, kind="scenario", with_document=False
            )
            change = (
                None
                if scenario_head is None
                else repo.get_scenario_change(
                    conn, scenario_version_id=scenario_head["id"]
                )
            )
        if baseline_head is None:
            raise NoSchedule(str(project_id))
        if scenario_head is not None and (
            change is None
            or change["baseline_version_id"] != baseline_head["id"]
            or change["scenario_version_id"] != scenario_head["id"]
        ):
            raise IntegrityError(
                f"scenario head {scenario_head['id']} is not derived from active "
                f"baseline {baseline_head['id']}"
            )
        baseline_working = _verify(project_id, baseline_head)
        baseline = self.latest_calculation(
            project_id, kind="baseline", version_id=baseline_head["id"]
        )
        scenario = (
            None
            if scenario_head is None
            else self.latest_calculation(
                project_id, kind="scenario", version_id=scenario_head["id"]
            )
        )
        if scenario_head is not None and (change is None or scenario is None):
            raise IntegrityError(
                f"scenario head {scenario_head['id']} has incomplete lineage or results"
            )
        if scenario is not None and baseline is not None and (
            _projected_context(scenario) != _projected_context(baseline)
        ):
            raise IntegrityError(
                f"scenario head {scenario_head['id']} was calculated under different "
                "engine or window provenance from the active baseline result"
            )

        # The result stores relationship assumptions/exclusions/releases beside
        # the activity rows rather than on them. Surface that context on both
        # endpoints before deciding whether a task is safe to edit, so the page
        # cannot call an edge-dependent answer "calculated normally" and PL14
        # cannot persist a scenario whose movement depends on an unevidenced
        # relationship rule.
        baseline = _with_relationship_context(baseline_working.schedule, baseline)
        scenario = _with_relationship_context(baseline_working.schedule, scenario)

        eligible: list[dict[str, Any]] = []
        if baseline is not None:
            results = {row["activity_uid"]: row for row in baseline["activities"]}
            for activity in baseline_working.schedule.activities:
                row = results.get(activity.uid)
                if (
                    activity.kind is ActivityKind.TASK
                    and activity.active
                    and not activity.manual
                    and activity.actual_start is None
                    and activity.actual_finish is None
                    and activity.planned_duration is not None
                    and activity.planned_duration.seconds > 0
                    and (
                        activity.remaining_duration is None
                        or activity.remaining_duration.seconds > 0
                    )
                    and row is not None
                    and row["disposition"] == SCHEDULED
                    and not row["assumptions"]
                ):
                    eligible.append(
                        {
                            "activity_uid": activity.uid,
                            "code": activity.code,
                            "name": activity.name,
                            "planned_duration_seconds": activity.planned_duration.seconds,
                        }
                    )
        current = scenario_head if scenario_head is not None else baseline_head
        return {
            "project_id": project_id,
            "project_name": project["name"],
            "baseline_version_id": baseline_head["id"],
            "current_version_id": current["id"],
            "current_kind": "scenario" if scenario_head is not None else "baseline",
            "baseline": baseline,
            "scenario": scenario,
            "change": (
                None
                if change is None
                else {
                    "change_id": change["id"],
                    "baseline_version_id": change["baseline_version_id"],
                    "scenario_version_id": change["scenario_version_id"],
                    "activity_uid": change["activity_uid"],
                    "field": change["field"],
                    "before_seconds": int(change["before_seconds"]),
                    "after_seconds": int(change["after_seconds"]),
                    "remaining_before_seconds": (
                        None
                        if change["remaining_before_seconds"] is None
                        else int(change["remaining_before_seconds"])
                    ),
                    "remaining_after_seconds": (
                        None
                        if change["remaining_after_seconds"] is None
                        else int(change["remaining_after_seconds"])
                    ),
                    "created_at": change["created_at"],
                }
            ),
            "eligible_activities": eligible,
        }

    def scenario_export(self, project_id: uuid.UUID) -> dict[str, Any]:
        """A labelled prototype state export; this is not an MSPDI writer."""

        state = self.planner_state(project_id)
        current = state["scenario"] or state["baseline"]
        if current is None:
            raise ScenarioRejected(
                "CALCULATION_REQUIRED", "calculate the baseline before exporting"
            )
        dispositions: dict[str, int] = {}
        assumption_codes: dict[str, int] = {}
        exclusion_codes: dict[str, int] = {}
        for row in current["activities"]:
            dispositions[row["disposition"]] = dispositions.get(row["disposition"], 0) + 1
            for code in row["assumptions"]:
                assumption_codes[code] = assumption_codes.get(code, 0) + 1
            if row["exclusion_code"]:
                code = row["exclusion_code"]
                exclusion_codes[code] = exclusion_codes.get(code, 0) + 1
        return {
            "format": "sto-prototype-scenario-state-1",
            "claim": "prototype scenario state; not a Microsoft Project round-trip",
            "project": {
                "id": state["project_id"],
                "name": state["project_name"],
            },
            "baseline_version_id": state["baseline_version_id"],
            "scenario_version_id": (
                None if state["change"] is None else state["change"]["scenario_version_id"]
            ),
            "current_version_id": state["current_version_id"],
            "current_kind": state["current_kind"],
            "change": state["change"],
            "calculation": {
                "id": current["calculation_id"],
                "canonical_hash": current["canonical_hash"],
                "fingerprint": current["fingerprint"],
                "profiles": current["profiles"],
                "dispositions": dispositions,
                "assumptions": assumption_codes,
                "exclusions": exclusion_codes,
            },
            "activities": current["activities"],
            "summaries": current["summaries"],
            "relationships": current["relationships"],
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

        # Refresh from the durable head so a retry after another process's
        # import does not keep deriving from this process's old resident copy.
        prior = self.load(project_id, refresh=True)
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
            if not repo.lock_project(conn, project_id):
                raise UnknownProject(str(project_id))
            current_prior = repo.head_version(
                conn, project_id=project_id, kind="baseline", with_document=False
            )
            expected_prior_id = None if prior is None else prior.version_id
            current_prior_id = None if current_prior is None else current_prior["id"]
            if current_prior_id != expected_prior_id:
                raise StaleSchedule(
                    f"baseline moved from {expected_prior_id} to {current_prior_id}; "
                    "retry the import against the current schedule"
                )
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
            # A scenario derives from one exact baseline.  A later import makes
            # that scenario historic and removes only its movable head; both
            # the scenario version and its calculation remain auditable.
            repo.delete_head(conn, project_id=project_id, kind="scenario")
            conn.commit()

        with self._state_lock:
            self._resident[project_id] = WorkingSchedule(
                project_id=project_id,
                version_id=version_id,
                sequence=sequence,
                canonical_hash=digest,
                schedule=schedule,
                identity=identity,
            )
            # A successful import supersedes any integrity diagnosis recorded
            # for the previous head, including one racing this commit.
            self.integrity_failures.pop(project_id, None)
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
        resource_calendars_apply=header["resource_calendars_apply"],
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
            exclusion_detail=row["exclusion_detail"],
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
