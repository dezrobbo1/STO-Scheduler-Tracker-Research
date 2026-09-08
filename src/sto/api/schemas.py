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
    summaries: int


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
    exclusion_code: str | None = None
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


class CalculationResponse(BaseModel):
    """A stored calculation, with every row as imported and as calculated."""

    project_id: uuid.UUID
    version_id: uuid.UUID
    calculation_id: uuid.UUID
    canonical_hash: str
    fingerprint: str
    horizon_start: datetime
    horizon_finish: datetime
    progress_policy: str
    critical_float_threshold: int
    profiles: dict[str, str]
    computed_at: datetime
    counts: dict[str, int]
    activities: list[ActivityRow]
    summaries: list[SummaryRow]
