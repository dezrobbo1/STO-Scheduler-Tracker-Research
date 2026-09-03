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
