"""Entities of the canonical schedule model, version 1.

One model has to be populated from Microsoft Project (MSPDI/MPP), Primavera
(XER/PMXML) and CMMS work-order extracts, and written back to each. Three
consequences shape what follows.

*   **WBS is first class, and summary tasks are a projection of it.** Primavera
    keeps a WBS hierarchy separate from activities; Microsoft Project expresses
    the same idea as summary tasks that also carry links, constraints and
    rollups. Modelling only one loses the other, so a :class:`WbsNode` may carry
    an :class:`MsSummaryProjection` describing the summary task it came from or
    should be written back as.

*   **Nothing calculated is stored as an input.** Early/late dates, float and
    criticality read from a source file live in
    :class:`SourceObservations`, which the engine never consumes and the file
    oracle compares against. Values the engine produces live in a separate
    result object entirely.

*   **Quantities are integers.** Durations and work are seconds; percentages and
    resource units are per-mille. Floats are refused at the hashing boundary,
    because a schedule whose hash depends on binary rounding cannot be compared
    across two runs.

Times are naive wall-clock local. Microsoft Project, Primavera and CMMS
extracts all store wall-clock, and converting on the way in is how a shutdown
that starts at 07:00 becomes one that starts at 06:00 in another time zone. The
site's IANA zone is recorded once on the schedule and never applied to values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from .enums import (
    ActivityKind,
    BaselineKind,
    CalendarType,
    ConstraintType,
    DurationType,
    LagCalendar,
    MilestoneSnapPolicy,
    PercentCompleteType,
    ProgressPolicy,
    RelationshipType,
    ResourceType,
    ScheduleDirection,
    SchedulingClass,
    SourceFormat,
    SourceSystem,
)

SCHEMA_VERSION = "sto-canonical-1.0"


@dataclass(frozen=True, slots=True)
class ExternalRef:
    """Where one entity came from, in the source system's own terms."""

    system: SourceSystem
    uid: str
    id: str | None = None
    guid: str | None = None
    snapshot_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """One import of one file."""

    snapshot_id: str
    system: SourceSystem
    format: SourceFormat
    file_sha256: str
    byte_length: int
    imported_at: datetime | None = None
    importer_profile: str | None = None
    document_name: str | None = None
    #: The application that wrote the file, and its build. The build is what a
    #: native round-trip evidence entry is keyed on: a transaction proven
    #: against one Microsoft Project build is not proven against another.
    application: str | None = None
    application_version: str | None = None
    #: MSPDI ``SaveVersion``: the file schema generation, not the build.
    save_version: int | None = None
    inventory: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Duration:
    """A span of working time.

    ``seconds`` is authoritative. ``unit`` and ``elapsed`` record how the source
    displayed it, because Microsoft Project's ``DurationFormat`` and Primavera's
    hour-decimals are presentation, not meaning, and round-tripping the display
    unit is what stops ``8h`` becoming ``1d`` on export.
    """

    seconds: int
    unit: str | None = None
    elapsed: bool = False
    source_format_code: int | None = None


@dataclass(frozen=True, slots=True)
class PercentComplete:
    """Progress as the source expressed it.

    Microsoft Project keeps duration, work and physical percentages side by side
    and picks one by earned-value method; Primavera nominates a single governing
    type. Both are representable, and ``type`` says which one governs.
    """

    type: PercentCompleteType = PercentCompleteType.DURATION
    duration_permille: int = 0
    work_permille: int = 0
    physical_permille: int = 0
    units_permille: int = 0


@dataclass(frozen=True, slots=True)
class Constraint:
    type: ConstraintType = ConstraintType.ASAP
    date: datetime | None = None
    hard: bool = False


@dataclass(frozen=True, slots=True)
class SourceObservations:
    """Calculated values the source file already held.

    These are never scheduling inputs. They exist so the file oracle can ask the
    only question that matters early on: does our engine reproduce what
    Microsoft Project or Primavera themselves computed for this file?
    """

    start: datetime | None = None
    finish: datetime | None = None
    early_start: datetime | None = None
    early_finish: datetime | None = None
    late_start: datetime | None = None
    late_finish: datetime | None = None
    total_float_seconds: int | None = None
    free_float_seconds: int | None = None
    critical: bool | None = None


@dataclass(frozen=True, slots=True)
class MsSummaryProjection:
    """How a WBS node appears, or should be written, as a summary task.

    Microsoft Project summary tasks can carry links, constraints, custom fields
    and notes that Primavera WBS nodes cannot. Keeping them here means a
    P6-origin schedule can still be written to MSPDI, and an MS-origin schedule
    does not lose them on the way through.
    """

    task_uid: str | None = None
    summary_milestone: bool = False
    external_id: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class WbsNode:
    uid: UUID
    code: str | None = None
    name: str = ""
    parent_uid: UUID | None = None
    seq: int = 0
    level: int = 0
    ms_projection: MsSummaryProjection | None = None
    external_refs: tuple[ExternalRef, ...] = ()
    source_observations: SourceObservations | None = None
    source_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActivityCodeAssignment:
    code_type_uid: UUID
    code_value_uid: UUID


@dataclass(frozen=True, slots=True)
class Activity:
    uid: UUID
    name: str = ""
    wbs_uid: UUID | None = None
    code: str | None = None
    kind: ActivityKind = ActivityKind.TASK
    seq: int = 0
    active: bool = True
    manual: bool = False
    duration_type: DurationType = DurationType.FIXED_DURATION
    effort_driven: bool = False
    planned_duration: Duration | None = None
    remaining_duration: Duration | None = None
    actual_duration: Duration | None = None
    planned_work: Duration | None = None
    percent_complete: PercentComplete = field(default_factory=PercentComplete)
    actual_start: datetime | None = None
    actual_finish: datetime | None = None
    suspend: datetime | None = None
    resume: datetime | None = None
    calendar_uid: UUID | None = None
    primary_constraint: Constraint | None = None
    secondary_constraint: Constraint | None = None
    deadline: datetime | None = None
    expected_finish: datetime | None = None
    priority: int | None = None
    levelling_delay_seconds: int = 0
    codes: tuple[ActivityCodeAssignment, ...] = ()
    udfs: dict[str, str] = field(default_factory=dict)
    notes: str | None = None
    external_refs: tuple[ExternalRef, ...] = ()
    source_observations: SourceObservations | None = None
    source_fields: dict[str, str] = field(default_factory=dict)

    @property
    def is_milestone(self) -> bool:
        return self.kind in (ActivityKind.START_MILESTONE, ActivityKind.FINISH_MILESTONE)


@dataclass(frozen=True, slots=True)
class Relationship:
    uid: UUID
    predecessor_uid: UUID
    successor_uid: UUID
    type: RelationshipType = RelationshipType.FS
    lag: Duration | None = None
    lag_calendar: LagCalendar = LagCalendar.INHERIT_PROJECT_POLICY
    seq: int = 0
    cross_project: bool = False
    cross_project_name: str | None = None
    external_refs: tuple[ExternalRef, ...] = ()
    source_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TimeInterval:
    """A working window inside a day, as seconds from midnight, half-open."""

    start_second: int
    finish_second: int


@dataclass(frozen=True, slots=True)
class CalendarWeekDay:
    """One of the seven weekday patterns. ``day`` is 1=Sunday .. 7=Saturday."""

    day: int
    working: bool
    intervals: tuple[TimeInterval, ...] = ()


@dataclass(frozen=True, slots=True)
class CalendarException:
    """A dated override of the weekly pattern.

    The research engine counted exceptions and refused to schedule any calendar
    whose exceptions fell inside the horizon. They are applied here, which is
    what lets a real shutdown calendar with 40 exceptions be scheduled at all.
    """

    from_date: datetime
    to_date: datetime
    working: bool
    intervals: tuple[TimeInterval, ...] = ()
    name: str | None = None
    recurrence: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Calendar:
    uid: UUID
    name: str = ""
    type: CalendarType = CalendarType.PROJECT
    base_uid: UUID | None = None
    week: tuple[CalendarWeekDay, ...] = ()
    exceptions: tuple[CalendarException, ...] = ()
    hours_per_day_seconds: int | None = None
    hours_per_week_seconds: int | None = None
    hours_per_month_seconds: int | None = None
    external_refs: tuple[ExternalRef, ...] = ()
    source_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Resource:
    uid: UUID
    name: str = ""
    code: str | None = None
    type: ResourceType = ResourceType.LABOR
    scheduling_class: SchedulingClass = SchedulingClass.RENEWABLE
    max_units_permille: int | None = None
    calendar_uid: UUID | None = None
    parent_uid: UUID | None = None
    group: str | None = None
    is_role: bool = False
    inactive: bool = False
    skills: tuple[str, ...] = ()
    location: str | None = None
    external_refs: tuple[ExternalRef, ...] = ()
    source_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UnitsTriple:
    budgeted_permille: int = 0
    actual_permille: int = 0
    remaining_permille: int = 0


@dataclass(frozen=True, slots=True)
class WorkTriple:
    budgeted_seconds: int = 0
    actual_seconds: int = 0
    remaining_seconds: int = 0


@dataclass(frozen=True, slots=True)
class Assignment:
    uid: UUID
    activity_uid: UUID | None = None
    resource_uid: UUID | None = None
    role_uid: UUID | None = None
    units: UnitsTriple = field(default_factory=UnitsTriple)
    work: WorkTriple = field(default_factory=WorkTriple)
    curve_uid: UUID | None = None
    start: datetime | None = None
    finish: datetime | None = None
    percent_work_complete_permille: int = 0
    #: Timephased rows are retained by reference; the payload stays with the
    #: source file rather than being re-encoded, because a lossy re-encoding
    #: proves nothing the original bytes do not.
    timephased_ref: str | None = None
    unassigned_placeholder: bool = False
    external_refs: tuple[ExternalRef, ...] = ()
    source_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActivityCodeType:
    uid: UUID
    name: str = ""
    scope: str = "project"
    max_length: int | None = None
    external_refs: tuple[ExternalRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ActivityCodeValue:
    uid: UUID
    code_type_uid: UUID
    value: str = ""
    description: str | None = None
    parent_uid: UUID | None = None
    seq: int = 0
    external_refs: tuple[ExternalRef, ...] = ()


@dataclass(frozen=True, slots=True)
class UdfDefinition:
    uid: UUID
    name: str = ""
    owner_kind: str = "activity"
    data_type: str = "text"
    alias: str | None = None
    ms_field_id: str | None = None
    p6_udf_type_id: str | None = None
    formula: str | None = None


@dataclass(frozen=True, slots=True)
class BaselineActivityState:
    activity_uid: UUID
    start: datetime | None = None
    finish: datetime | None = None
    duration_seconds: int | None = None
    work_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class Baseline:
    uid: UUID
    name: str = ""
    kind: BaselineKind = BaselineKind.MS_BASELINE
    number: int = 0
    captured_at: datetime | None = None
    source_snapshot_id: str | None = None
    activity_states: tuple[BaselineActivityState, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    name: str = ""
    start: datetime | None = None
    finish: datetime | None = None
    status_date: datetime | None = None
    must_finish_by: datetime | None = None
    schedule_direction: ScheduleDirection = ScheduleDirection.FROM_START
    progress_policy: ProgressPolicy = ProgressPolicy.RETAINED_LOGIC
    lag_calendar_policy: LagCalendar = LagCalendar.SUCCESSOR
    milestone_snap_policy: MilestoneSnapPolicy = MilestoneSnapPolicy.NONE
    default_calendar_uid: UUID | None = None
    critical_float_threshold_seconds: int = 0
    minutes_per_day: int | None = None
    minutes_per_week: int | None = None
    days_per_month: int | None = None
    #: IANA zone for the site. Recorded, never applied: values stay wall-clock.
    timezone: str | None = None
    source_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Schedule:
    """The whole canonical document."""

    schedule_id: str
    schema_version: str = SCHEMA_VERSION
    project: ProjectSettings = field(default_factory=ProjectSettings)
    snapshots: tuple[SourceSnapshot, ...] = ()
    wbs_nodes: tuple[WbsNode, ...] = ()
    activities: tuple[Activity, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    calendars: tuple[Calendar, ...] = ()
    resources: tuple[Resource, ...] = ()
    assignments: tuple[Assignment, ...] = ()
    code_types: tuple[ActivityCodeType, ...] = ()
    code_values: tuple[ActivityCodeValue, ...] = ()
    udf_definitions: tuple[UdfDefinition, ...] = ()
    baselines: tuple[Baseline, ...] = ()

    def activity_by_uid(self) -> dict[UUID, Activity]:
        return {activity.uid: activity for activity in self.activities}

    def calendar_by_uid(self) -> dict[UUID, Calendar]:
        return {calendar.uid: calendar for calendar in self.calendars}

    def counts(self) -> dict[str, int]:
        return {
            "wbs_nodes": len(self.wbs_nodes),
            "activities": len(self.activities),
            "relationships": len(self.relationships),
            "calendars": len(self.calendars),
            "resources": len(self.resources),
            "assignments": len(self.assignments),
            "code_types": len(self.code_types),
            "code_values": len(self.code_values),
            "udf_definitions": len(self.udf_definitions),
            "baselines": len(self.baselines),
        }
