"""Vocabulary for the canonical schedule model.

Values are the strings that appear in serialised documents and, later, in the
database CHECK constraints. They are stable: renaming one is a schema-version
change, not a refactor.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Enum whose members serialise as their value."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class SourceSystem(StrEnum):
    MICROSOFT_PROJECT = "MicrosoftProject"
    PRIMAVERA_P6 = "PrimaveraP6"
    SAP_PM = "SAP_PM"
    MAXIMO = "Maximo"
    ORACLE_EAM = "OracleEAM"
    STO = "STO"


class SourceFormat(StrEnum):
    MSPDI = "MSPDI"
    MPP = "MPP"
    XER = "XER"
    PMXML = "PMXML"
    CSV = "CSV"
    XLSX = "XLSX"
    API = "API"


class EntityKind(StrEnum):
    PROJECT = "project"
    WBS_NODE = "wbs_node"
    ACTIVITY = "activity"
    RELATIONSHIP = "relationship"
    CALENDAR = "calendar"
    RESOURCE = "resource"
    ROLE = "role"
    ASSIGNMENT = "assignment"
    CURVE = "curve"
    CODE_TYPE = "code_type"
    CODE_VALUE = "code_value"
    UDF = "udf"
    BASELINE = "baseline"
    WORK_ORDER = "work_order"
    OPERATION = "operation"


class ActivityKind(StrEnum):
    """What the row is. Milestones and summaries are not scheduled like tasks."""

    TASK = "task"
    START_MILESTONE = "start_milestone"
    FINISH_MILESTONE = "finish_milestone"
    LEVEL_OF_EFFORT = "level_of_effort"
    WBS_SUMMARY = "wbs_summary"
    HAMMOCK = "hammock"


class DurationType(StrEnum):
    """Which of duration, units and work the scheduler holds fixed."""

    FIXED_DURATION = "fixed_duration"
    FIXED_DURATION_AND_UNITS = "fixed_duration_and_units"
    FIXED_UNITS = "fixed_units"
    FIXED_WORK = "fixed_work"


class PercentCompleteType(StrEnum):
    DURATION = "duration"
    PHYSICAL = "physical"
    UNITS = "units"
    WORK = "work"


class ConstraintType(StrEnum):
    ASAP = "asap"
    ALAP = "alap"
    SNET = "start_no_earlier_than"
    SNLT = "start_no_later_than"
    FNET = "finish_no_earlier_than"
    FNLT = "finish_no_later_than"
    MSO = "must_start_on"
    MFO = "must_finish_on"


class RelationshipType(StrEnum):
    FS = "FS"
    SS = "SS"
    FF = "FF"
    SF = "SF"


class LagCalendar(StrEnum):
    """Whose working time a lag is measured in.

    Microsoft Project has no setting for this; Primavera does, per project.
    ``INHERIT_PROJECT_POLICY`` means the schedule-level policy applies.
    """

    PREDECESSOR = "predecessor"
    SUCCESSOR = "successor"
    PROJECT = "project"
    ELAPSED_24H = "elapsed_24h"
    INHERIT_PROJECT_POLICY = "inherit_project_policy"


class CalendarType(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"
    RESOURCE = "resource"
    SHIFT = "shift"
    BASE = "base"


class ResourceType(StrEnum):
    LABOR = "labor"
    NONLABOR = "nonlabor"
    MATERIAL = "material"
    COST = "cost"


class SchedulingClass(StrEnum):
    """How the levelling stage may treat a resource."""

    RENEWABLE = "renewable"
    EXCLUSIVE = "exclusive"
    CUMULATIVE = "cumulative"
    NON_RENEWABLE = "non_renewable"


class ProgressPolicy(StrEnum):
    """How reported progress interacts with network logic."""

    NONE = "none"
    RETAINED_LOGIC = "retained_logic"
    PROGRESS_OVERRIDE = "progress_override"
    ACTUAL_DATES = "actual_dates"


class ScheduleDirection(StrEnum):
    FROM_START = "from_start"
    FROM_FINISH = "from_finish"


class MilestoneSnapPolicy(StrEnum):
    """Whether a milestone is pulled to the next working instant.

    Microsoft Project leaves it where the predecessor left it; Primavera and the
    reference semantics snap it. Recording the choice keeps a re-import from
    silently changing dates.
    """

    NONE = "none"
    NEXT_WORKING = "next_working"


class BaselineKind(StrEnum):
    MS_BASELINE = "ms_baseline"
    P6_PROJECT_BASELINE = "p6_project_baseline"
    STO_SNAPSHOT = "sto_snapshot"


class ReconciliationOutcome(StrEnum):
    MATCHED = "matched"
    NEW = "new"
    MISSING = "missing"
    REKEYED = "rekeyed"
