"""Request and response shapes. Mapped to and from core dataclasses at the edge."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    description: str | None = None


class ScheduleHead(BaseModel):
    version_id: uuid.UUID
    sequence: int
    kind: str
    canonical_hash: str
    schema_version: str
    engine_profile: str | None
    cause_type: str
    created_at: datetime


class Project(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    timezone: str
    created_at: datetime
    baseline: ScheduleHead | None = None


class Reconciliation(BaseModel):
    matched: int
    new: int
    rekeyed: int
    missing: int
    guid_changed: int
    #: Rows whose GUID had already been seen in the same document, resolved on
    #: their own source UID rather than conflated with the row that came first.
    guid_duplicated_in_snapshot: int = 0


class ImportResponse(BaseModel):
    project_id: uuid.UUID
    import_batch_id: uuid.UUID
    version_id: uuid.UUID
    sequence: int
    canonical_hash: str
    source_sha256: str
    reconciliation: Reconciliation
    project_identity_mismatch: bool
    declared_project_guid: str | None
    #: What the importer warned about while accepting the file. An accepted
    #: import is not necessarily a clean one, and the caller is told which.
    warnings: list[str] = []


class ScheduleResponse(BaseModel):
    project_id: uuid.UUID
    version_id: uuid.UUID
    sequence: int
    canonical_hash: str
    schedule_id: str
    counts: dict[str, int]
    document: dict | None = None


class Health(BaseModel):
    status: str
    database: str
    resident_projects: int
    integrity_failures: dict[uuid.UUID, str] = Field(default_factory=dict)


class CalculationSummary(BaseModel):
    """A calculation that has been stored, and what produced it."""

    project_id: uuid.UUID
    version_id: uuid.UUID
    calculation_id: uuid.UUID
    canonical_hash: str
    fingerprint: str
    scheduled: int
    excluded: int
    #: Every WBS row stored, a branch with nothing beneath it included, so this
    #: agrees with the calculation read back.
    summaries: int
    #: True when this run was already stored. A calculation is deterministic,
    #: so asking twice is not an error and does not make a second row.
    already_stored: bool = False


class ActivityRow(BaseModel):
    """One activity, as imported and as calculated, side by side.

    The two are kept apart deliberately. ``source_*`` is what the file said and
    is never recomputed; the rest is what this engine worked out. A reader
    comparing them is the point of the row, and a row that blended them could
    not be compared at all.
    """

    activity_uid: uuid.UUID
    code: str | None = None
    name: str | None = None
    disposition: str
    source_start: datetime | None = None
    source_finish: datetime | None = None
    early_start: datetime | None = None
    early_finish: datetime | None = None
    late_start: datetime | None = None
    late_finish: datetime | None = None
    remaining_start: datetime | None = None
    total_float_seconds: int | None = None
    free_float_seconds: int | None = None
    critical: bool | None = None
    progress_state: str | None = None
    placed_by: str | None = None
    #: What bounded the late span, which in a chain is a different edge from
    #: what bounded the early one.
    late_placed_by: str | None = None
    #: A hard constraint that overrode precedence, and what the logic wanted.
    constraint_override: str | None = None
    exclusion_code: str | None = None
    #: What the code alone cannot say: which predecessor, which duration.
    exclusion_detail: str | None = None
    assumptions: list[str] = []
    agrees_with_source: bool | None = None


class SummaryRow(BaseModel):
    """One WBS node's rolled-up span, beside the one the file stored."""

    wbs_uid: uuid.UUID
    code: str | None = None
    name: str | None = None
    span_start: datetime | None = None
    span_finish: datetime | None = None
    placed: int = 0
    source_start: datetime | None = None
    source_finish: datetime | None = None


class RelationshipRow(BaseModel):
    """An edge the plan dropped, or kept under a labelled rule.

    An edge has no dates of its own, so it is not a row of the schedule. It is
    here because it decided the dates that are: a reader looking at an activity
    that did not move where they expected needs to see the edge that was
    dropped, or the rule the lag was measured under.
    """

    relationship_uid: uuid.UUID
    disposition: str
    code: str
    detail: str = ""


class CalculationResponse(BaseModel):
    """A stored calculation, with every row as imported and as calculated."""

    project_id: uuid.UUID
    version_id: uuid.UUID
    calculation_id: uuid.UUID
    canonical_hash: str
    fingerprint: str
    epoch: datetime
    horizon_start: datetime
    horizon_finish: datetime
    progress_policy: str
    critical_float_threshold: int
    #: The status date the passes used, and whether the file carried one that
    #: fell outside the compiled window and was dropped. Without the second, a
    #: run with discarded progress context reads as a run that never had any.
    status_time: datetime | None = None
    status_time_outside_window: bool = False
    resource_calendars_apply: bool
    profiles: dict[str, str]
    computed_at: datetime
    counts: dict[str, int]
    relationships: list[RelationshipRow] = []
    activities: list[ActivityRow]
    summaries: list[SummaryRow]


class ScenarioEdit(BaseModel):
    expected_version_id: uuid.UUID
    activity_uid: uuid.UUID
    planned_duration_seconds: int = Field(gt=0, strict=True)


class ScenarioReset(BaseModel):
    expected_version_id: uuid.UUID


class ScenarioChange(BaseModel):
    change_id: uuid.UUID
    baseline_version_id: uuid.UUID
    scenario_version_id: uuid.UUID
    activity_uid: uuid.UUID
    field: str
    before_seconds: int
    after_seconds: int
    remaining_before_seconds: int | None = None
    remaining_after_seconds: int | None = None
    created_at: datetime


class EligibleActivity(BaseModel):
    activity_uid: uuid.UUID
    code: str | None = None
    name: str
    planned_duration_seconds: int


class PlannerState(BaseModel):
    project_id: uuid.UUID
    project_name: str
    baseline_version_id: uuid.UUID
    current_version_id: uuid.UUID
    current_kind: str
    baseline: CalculationResponse | None = None
    scenario: CalculationResponse | None = None
    change: ScenarioChange | None = None
    eligible_activities: list[EligibleActivity] = []
