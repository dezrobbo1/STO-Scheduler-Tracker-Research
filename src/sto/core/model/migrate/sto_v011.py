"""Migrate a research-importer document (``mspdi-import-v0.1.1``) to canonical v1.

The research importer produced an untyped, MSPDI-shaped dictionary: lags in
tenths of a minute, Microsoft's integer task ``Type``, calculated values mixed
in beside inputs as ``*_source`` keys, and document-local identifiers. This
module turns one of those into a typed :class:`~sto.core.model.entities.Schedule`
with durable identity, so the existing importer keeps earning its place as an
oracle while everything downstream speaks canonical.

Nothing is invented here. Where the source has no answer -- a lag calendar for a
Microsoft file, say -- the field carries the policy value that says so rather
than a guess.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from uuid import UUID

from ..enums import (
    ActivityKind,
    BaselineKind,
    CalendarType,
    ConstraintType,
    DurationType,
    EntityKind,
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
from ..entities import (
    Activity,
    Assignment,
    Baseline,
    BaselineActivityState,
    Calendar,
    CalendarException,
    CalendarWeekDay,
    Constraint,
    Duration,
    ExternalRef,
    MsSummaryProjection,
    PercentComplete,
    ProjectSettings,
    Relationship,
    Resource,
    Schedule,
    SourceObservations,
    SourceSnapshot,
    TimeInterval,
    UdfDefinition,
    UnitsTriple,
    WbsNode,
    WorkTriple,
)
from ..ids import (
    IdentityMap,
    ReconciliationEntry,
    ReconciliationReport,
    normalise_guid,
)

SUPPORTED_IMPORTER_PROFILES = frozenset({"mspdi-import-v0.1.1"})

#: Microsoft ``Task/Type``. Fixed Units is the Project default when omitted.
_MS_TASK_TYPE: dict[int, DurationType] = {
    0: DurationType.FIXED_UNITS,
    1: DurationType.FIXED_DURATION,
    2: DurationType.FIXED_WORK,
}

#: Microsoft ``Task/ConstraintType``.
_MS_CONSTRAINT: dict[int, ConstraintType] = {
    0: ConstraintType.ASAP,
    1: ConstraintType.ALAP,
    2: ConstraintType.MSO,
    3: ConstraintType.MFO,
    4: ConstraintType.SNET,
    5: ConstraintType.SNLT,
    6: ConstraintType.FNET,
    7: ConstraintType.FNLT,
}

#: Microsoft ``PredecessorLink/LagFormat`` codes that mean elapsed time. An
#: elapsed lag runs on the clock, not on the successor's working calendar, and
#: the distinction is why a -28ed lead lands where it does on the BOILER file.
_MS_ELAPSED_LAG_FORMATS = frozenset({4, 6, 8, 10, 12, 20})


class MigrationError(ValueError):
    """Raised when a document cannot be migrated."""


def _dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.utcoffset() is not None:
        raise MigrationError(
            f"timezone-aware source date is outside the canonical wall-clock contract: {value!r}"
        )
    return parsed


def _time_interval(interval: dict[str, Any], where: str) -> TimeInterval:
    """A working window with both bounds present. Nothing is invented here."""

    raw_from, raw_to = interval.get("from"), interval.get("to")
    if not raw_from or not raw_to:
        raise MigrationError(f"{where}: working time is missing a bound: {interval!r}")
    start = _seconds_of_day(raw_from)
    finish = _seconds_of_day(raw_to)
    return TimeInterval(start_second=start, finish_second=finish or 86400)


def _exception_from_row(entry: dict[str, Any], where: str) -> CalendarException:
    from_date, to_date = _dt(entry.get("from")), _dt(entry.get("to"))
    if from_date is None or to_date is None:
        raise MigrationError(f"{where}: calendar exception without a date range: {entry!r}")
    raw = {child.get("name"): child.get("text") for child in (entry.get("raw") or {}).get("children", [])}
    recurrence = {"source": "exception"}
    if entry.get("type") is not None:
        recurrence["type"] = str(entry["type"])
    if raw.get("Period") not in (None, ""):
        recurrence["period"] = str(raw["Period"])
    if entry.get("occurrences") is not None:
        recurrence["occurrences"] = str(entry["occurrences"])
    if entry.get("entered_by_occurrences") is not None:
        recurrence["entered_by_occurrences"] = "1" if entry["entered_by_occurrences"] else "0"
    return CalendarException(
        from_date=from_date,
        to_date=to_date,
        working=bool(entry.get("working")),
        intervals=tuple(
            _time_interval(interval, where) for interval in entry.get("working_times", [])
        ),
        name=entry.get("name"),
        recurrence=recurrence,
    )


def _special_day_from_row(day: dict[str, Any], where: str) -> CalendarException:
    """A legacy ``DayType 0`` entry: one dated override carried as a TimePeriod."""

    periods = [e for e in day.get("extensions", []) if e.get("name") == "TimePeriod"]
    if len(periods) != 1:
        raise MigrationError(f"{where}: special day without exactly one TimePeriod")
    bounds = {c.get("name"): c.get("text") for c in periods[0].get("children", [])}
    from_date, to_date = _dt(bounds.get("FromDate")), _dt(bounds.get("ToDate"))
    if from_date is None or to_date is None:
        raise MigrationError(f"{where}: special day without a date range")
    return CalendarException(
        from_date=from_date,
        to_date=to_date,
        working=bool(day.get("working")),
        intervals=tuple(_time_interval(i, where) for i in day.get("working_times", [])),
        name=None,
        recurrence={"source": "special_day", "type": "1"},
    )


def _seconds_of_day(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, time):
        parsed = value
    else:
        parsed = time.fromisoformat(str(value))
    return parsed.hour * 3600 + parsed.minute * 60 + parsed.second


def _duration(payload: Any) -> Duration | None:
    """Convert the importer's ``{raw, seconds, parse_status}`` block."""

    if not isinstance(payload, dict):
        return None
    seconds = payload.get("seconds")
    if seconds is None:
        return None
    return Duration(seconds=int(seconds), unit=None, elapsed=False)


def _permille(value: Any) -> int:
    """Percentages arrive as whole percent; per-mille keeps them integral."""

    if value is None:
        return 0
    return int(round(float(value) * 10))


def _ref(system: SourceSystem, row: dict[str, Any], snapshot_sha: str | None) -> ExternalRef:
    external = {
        entry.get("type"): entry.get("value")
        for entry in row.get("external_references", [])
        if isinstance(entry, dict)
    }
    return ExternalRef(
        system=system,
        uid=str(external.get("UID") or external.get("FieldID") or ""),
        id=str(external["ID"]) if external.get("ID") is not None else None,
        guid=normalise_guid(str(external["GUID"]))
        if external.get("GUID") is not None
        else None,
        snapshot_sha256=snapshot_sha,
    )


def _external(row: dict[str, Any], kind: str) -> str | None:
    for entry in row.get("external_references", []):
        if isinstance(entry, dict) and entry.get("type") == kind:
            value = entry.get("value")
            return None if value is None else str(value)
    return None


def _observations(row: dict[str, Any]) -> SourceObservations | None:
    """Lift the calculated values Microsoft Project already stored.

    Slack arrives in tenths of a minute, which is six seconds -- the unit that
    makes a naive comparison off by a factor of ten.
    """

    def slack(key: str) -> int | None:
        raw = row.get(key)
        return None if raw is None else int(raw) * 6

    observations = SourceObservations(
        start=_dt(row.get("start")),
        finish=_dt(row.get("finish")),
        early_start=_dt(row.get("early_start_source")),
        early_finish=_dt(row.get("early_finish_source")),
        late_start=_dt(row.get("late_start_source")),
        late_finish=_dt(row.get("late_finish_source")),
        total_float_seconds=slack("total_slack_tenths_minutes_source"),
        free_float_seconds=slack("free_slack_tenths_minutes_source"),
        critical=row.get("critical_source"),
    )
    return observations if observations != SourceObservations() else None


#: MSPDI's own default when a file omits ``MinutesPerDay``.
_DEFAULT_MINUTES_PER_DAY = 480


def _critical_threshold(project_row: dict[str, Any]) -> int:
    """``CriticalSlackLimit`` in seconds: days of the project's own working day.

    Microsoft Project stores the limit as a whole number of days and means
    *working* days of ``MinutesPerDay``, not calendar days. Measured, not
    assumed: the CALCINER schedule is the one file in this estate that sets the
    limit -- it declares six against a 480-minute day -- and at 172,800 seconds
    the rule ``total float <= threshold`` reproduces the ``Critical`` flag
    Project stored for all 1,763 of its activities, where ignoring the limit
    reproduces 1,478 and reading the six as calendar days reproduces 1,623. The
    file's own flags bracket the threshold to [156,600, 201,600) seconds, which
    contains the working-day reading and excludes both others.
    """

    limit = project_row.get("critical_slack_limit_source")
    if limit is None:
        return 0
    minutes = project_row.get("minutes_per_day") or _DEFAULT_MINUTES_PER_DAY
    return int(limit) * int(minutes) * 60


def _lag_calendar(lag_format: Any) -> LagCalendar:
    if lag_format is not None and int(lag_format) in _MS_ELAPSED_LAG_FORMATS:
        return LagCalendar.ELAPSED_24H
    return LagCalendar.INHERIT_PROJECT_POLICY


def _activity_kind(row: dict[str, Any], duration: Duration | None) -> ActivityKind:
    if not row.get("milestone_source"):
        return ActivityKind.TASK
    # A non-zero-duration row must remain schedulable work even if Project also
    # carries the display milestone flag. Treating it as a milestone would make
    # the canonical model internally contradictory.
    if duration is not None and duration.seconds != 0:
        return ActivityKind.TASK
    # Microsoft marks both ends of a zero-duration task as a milestone; the
    # finish variety is the one planners mean, and the one Project draws.
    return ActivityKind.FINISH_MILESTONE


def _constraint(row: dict[str, Any]) -> Constraint | None:
    code = row.get("constraint_type_source")
    if code is None:
        return None
    constraint_type = _MS_CONSTRAINT.get(int(code))
    if constraint_type is None:
        return None
    if constraint_type is ConstraintType.ASAP:
        return None
    return Constraint(
        type=constraint_type,
        date=_dt(row.get("constraint_date_source")),
        hard=constraint_type in (ConstraintType.MSO, ConstraintType.MFO),
    )


def _duration_type(code: Any) -> DurationType:
    """Translate Microsoft ``Task/Type`` without guessing unknown values."""

    if code is None:
        return DurationType.FIXED_UNITS
    try:
        value = int(code)
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"invalid Microsoft task Type: {code!r}") from exc
    try:
        return _MS_TASK_TYPE[value]
    except KeyError as exc:
        raise MigrationError(f"unsupported Microsoft task Type: {value}") from exc


def _resource_type(code: Any) -> ResourceType:
    """Microsoft ``Resource/Type``: 0 material, 1 work, 2 cost."""

    if code is None:
        return ResourceType.LABOR
    try:
        value = int(code)
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"invalid Microsoft resource Type: {code!r}") from exc
    mapping = {
        0: ResourceType.MATERIAL,
        1: ResourceType.LABOR,
        2: ResourceType.COST,
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise MigrationError(f"unsupported Microsoft resource Type: {value}") from exc


def _percent(row: dict[str, Any]) -> PercentComplete:
    return PercentComplete(
        type=PercentCompleteType.DURATION,
        duration_permille=_permille(row.get("percent_complete_source")),
        work_permille=_permille(row.get("percent_work_complete_source")),
        physical_permille=_permille(row.get("physical_percent_complete_source")),
    )


def _udf_values(row: dict[str, Any], alias_of: dict[str, str]) -> dict[str, str]:
    """Key custom-field values by their alias where the file names one.

    The site's own convention lives here: ``Text4`` is aliased "Work Order No."
    and ``Text5`` "Operation No.", which is the key a CMMS import links on.
    """

    values: dict[str, str] = {}
    for entry in row.get("custom_fields", []) or []:
        if not isinstance(entry, dict):
            continue
        field_id = str(entry.get("field_id"))
        value = entry.get("value")
        if value is None:
            continue
        values[alias_of.get(field_id, field_id)] = str(value)
    return values


def migrate(
    document: dict[str, Any],
    *,
    identity: IdentityMap | None = None,
    schedule_id: str | None = None,
) -> tuple[Schedule, IdentityMap, ReconciliationReport]:
    """Migrate one importer document.

    Passing the :class:`IdentityMap` returned by an earlier migration is what
    makes a re-import a re-import: rows keep the identifiers they had, and the
    report says what changed. A supplied map is copied first, so a failed
    migration cannot partially mutate durable identity state.
    """

    profile = document.get("importer_profile")
    if profile not in SUPPORTED_IMPORTER_PROFILES:
        raise MigrationError(f"unsupported importer profile: {profile!r}")

    system = SourceSystem.MICROSOFT_PROJECT
    source = document.get("source", {})
    project_row = document.get("project", {})
    snapshot_sha = source.get("sha256")
    snapshot_id = str(source.get("document_key") or source.get("sha256") or "")
    project_guid = normalise_guid(_external(project_row, "GUID"))

    if identity is None:
        resolved_id = schedule_id or project_guid or str(source.get("sha256"))
        identity = IdentityMap(schedule_id=resolved_id, system=system)
    else:
        if identity.system is not system:
            raise MigrationError(
                f"identity map source system {identity.system} does not match {system}"
            )
        if schedule_id is not None and schedule_id != identity.schedule_id:
            raise MigrationError(
                "explicit schedule_id does not match the supplied identity map: "
                f"{schedule_id!r} != {identity.schedule_id!r}"
            )
        resolved_id = identity.schedule_id
        identity = identity.clone()

    entries: list[ReconciliationEntry] = []
    seen: dict[EntityKind, list[str]] = {}

    def uid_for(kind: EntityKind, row: dict[str, Any], external_uid: str | None = None) -> UUID:
        external = external_uid if external_uid is not None else _external(row, "UID")
        if external is None:
            external = str(row.get("id"))
        uid, entry = identity.resolve(
            kind,
            external,
            guid=normalise_guid(_external(row, "GUID")),
        )
        entries.append(entry)
        seen.setdefault(kind, []).append(entry.external_uid)
        return uid

    # --- calendars -------------------------------------------------------
    calendar_uid_by_ref: dict[str, UUID] = {}
    calendars: list[Calendar] = []
    for row in document.get("calendars", []):
        uid = uid_for(EntityKind.CALENDAR, row)
        calendar_uid_by_ref[str(row.get("id"))] = uid

    for row in document.get("calendars", []):
        where = f"calendar {row.get('id')}"
        week_days: list[CalendarWeekDay] = []
        special_days: list[CalendarException] = []
        for day in row.get("week_days", []):
            day_type = day.get("day_type")
            if day_type is None:
                raise MigrationError(f"{where}: weekday without a DayType")
            day_type = int(day_type)
            if day_type == 0:
                # Older Project versions wrote dated overrides as weekday 0.
                special_days.append(_special_day_from_row(day, where))
                continue
            if day_type not in range(1, 8):
                raise MigrationError(f"{where}: DayType {day_type} is not a weekday")
            week_days.append(
                CalendarWeekDay(
                    day=day_type,
                    working=bool(day.get("working")),
                    intervals=tuple(
                        _time_interval(interval, f"{where} day {day_type}")
                        for interval in day.get("working_times", [])
                    ),
                )
            )
        week = tuple(week_days)
        exceptions = tuple(
            [_exception_from_row(entry, where) for entry in row.get("exceptions", [])]
            + special_days
        )
        base_ref = row.get("base_calendar_ref")
        calendars.append(
            Calendar(
                uid=calendar_uid_by_ref[str(row.get("id"))],
                name=row.get("name") or "",
                type=CalendarType.BASE if row.get("is_base") else CalendarType.PROJECT,
                base_uid=calendar_uid_by_ref.get(str(base_ref)) if base_ref else None,
                week=week,
                exceptions=exceptions,
                external_refs=(_ref(system, row, snapshot_sha),),
            )
        )

    # --- custom field definitions ---------------------------------------
    alias_of: dict[str, str] = {}
    udf_definitions: list[UdfDefinition] = []
    for row in document.get("custom_field_definitions", []):
        field_id = str(row.get("field_id"))
        alias = row.get("alias")
        if alias:
            alias_of[field_id] = str(alias)
        udf_definitions.append(
            UdfDefinition(
                uid=uid_for(EntityKind.UDF, row, external_uid=field_id),
                name=str(row.get("field_name") or field_id),
                owner_kind="activity",
                data_type="text",
                alias=str(alias) if alias else None,
                ms_field_id=field_id,
                formula=row.get("formula"),
            )
        )

    # --- WBS -------------------------------------------------------------
    wbs_uid_by_ref: dict[str, UUID] = {}
    for row in document.get("wbs_nodes", []):
        wbs_uid_by_ref[str(row.get("id"))] = uid_for(EntityKind.WBS_NODE, row)

    wbs_nodes: list[WbsNode] = []
    for row in document.get("wbs_nodes", []):
        parent_ref = row.get("parent_id")
        wbs_nodes.append(
            WbsNode(
                uid=wbs_uid_by_ref[str(row.get("id"))],
                code=row.get("wbs") or row.get("outline_number"),
                name=row.get("name") or "",
                parent_uid=wbs_uid_by_ref.get(str(parent_ref)) if parent_ref else None,
                seq=int(row.get("source_order") or 0),
                level=int(row.get("outline_level") or 0),
                ms_projection=MsSummaryProjection(
                    task_uid=_external(row, "UID"),
                    summary_milestone=bool(row.get("milestone_source")),
                    external_id=_external(row, "ID"),
                    notes=row.get("notes"),
                ),
                external_refs=(_ref(system, row, snapshot_sha),),
                source_observations=_observations(row),
            )
        )

    # --- activities ------------------------------------------------------
    extension_by_id = {
        item["id"]: item for item in document.get("vendor_extensions", [])
    }

    def source_fields_for(row: dict[str, Any], duration: Duration | None) -> dict[str, str]:
        """Source facts the engine reads that have no canonical field of their own.

        ``IgnoreResourceCalendar`` decides which calendar Microsoft Project
        schedules a task on -- see :func:`sto.core.engine.plan.build_plan` --
        and is carried here, as the milestone flag already is, rather than
        widening the canonical model for one vendor's switch. Only a set flag is
        recorded; an absent or clear one leaves the row as it was.
        """

        fields: dict[str, str] = {}
        if row.get("milestone_source") and duration is not None and duration.seconds != 0:
            fields["milestone_source"] = "true"
        values = [
            extension_by_id[ref].get("payload", {}).get("text")
            for ref in row.get("extension_refs", [])
            if ref in extension_by_id
            and extension_by_id[ref].get("payload", {}).get("name") == "IgnoreResourceCalendar"
        ]
        if len(values) == 1 and values[0] == "1":
            fields["ignore_resource_calendar_source"] = "1"
        return fields

    activity_uid_by_ref: dict[str, UUID] = {}
    activities: list[Activity] = []
    for row in document.get("activities", []):
        uid = uid_for(EntityKind.ACTIVITY, row)
        activity_uid_by_ref[str(row.get("id"))] = uid
        duration = _duration(row.get("duration"))
        parent_ref = row.get("parent_wbs_id")
        calendar_ref = row.get("calendar_ref")
        activities.append(
            Activity(
                uid=uid,
                name=row.get("name") or "",
                wbs_uid=wbs_uid_by_ref.get(str(parent_ref)) if parent_ref else None,
                code=row.get("wbs") or row.get("outline_number"),
                kind=_activity_kind(row, duration),
                seq=int(row.get("source_order") or 0),
                active=True if row.get("active") is None else bool(row.get("active")),
                manual=bool(row.get("manual", False)),
                duration_type=_duration_type(row.get("source_task_type")),
                effort_driven=bool(row.get("effort_driven_source", False)),
                planned_duration=duration,
                remaining_duration=_duration(row.get("remaining_duration_source")),
                actual_duration=_duration(row.get("actual_duration_source")),
                planned_work=_duration(row.get("work")),
                percent_complete=_percent(row),
                actual_start=_dt(row.get("actual_start_source")),
                actual_finish=_dt(row.get("actual_finish_source")),
                calendar_uid=calendar_uid_by_ref.get(str(calendar_ref)) if calendar_ref else None,
                primary_constraint=_constraint(row),
                deadline=_dt(row.get("deadline_source")),
                priority=row.get("priority"),
                udfs=_udf_values(row, alias_of),
                notes=row.get("notes"),
                external_refs=(_ref(system, row, snapshot_sha),),
                source_observations=_observations(row),
                source_fields=source_fields_for(row, duration),
            )
        )

    # --- relationships ---------------------------------------------------
    node_uid = {**wbs_uid_by_ref, **activity_uid_by_ref}
    relationships: list[Relationship] = []
    for row in document.get("relationships", []):
        predecessor = node_uid.get(str(row.get("predecessor_ref")))
        successor = node_uid.get(str(row.get("successor_ref")))
        if predecessor is None or successor is None:
            # The importer already refuses documents with dangling endpoints;
            # a survivor here would be a defect, not data.
            continue
        relationship_type = RelationshipType(str(row.get("type")))
        # The importer's id is ``relationship:{successor}:{ordinal}``, and
        # document-local endpoint refs can also change when a task is rekeyed.
        # Canonical endpoints + type identify the same logical link across both.
        relationship_key = "|".join(
            (str(predecessor), str(successor), str(relationship_type))
        )
        uid, entry = identity.resolve(EntityKind.RELATIONSHIP, relationship_key)
        entries.append(entry)
        seen.setdefault(EntityKind.RELATIONSHIP, []).append(entry.external_uid)
        lag_seconds = int(row.get("lag_seconds") or 0)
        lag_format = row.get("lag_format_source")
        relationships.append(
            Relationship(
                uid=uid,
                predecessor_uid=predecessor,
                successor_uid=successor,
                type=relationship_type,
                lag=Duration(
                    seconds=lag_seconds,
                    elapsed=lag_format is not None
                    and int(lag_format) in _MS_ELAPSED_LAG_FORMATS,
                    source_format_code=None if lag_format is None else int(lag_format),
                )
                if lag_seconds or lag_format is not None
                else None,
                lag_calendar=_lag_calendar(lag_format),
                seq=int(row.get("source_order") or 0),
                cross_project=bool(row.get("cross_project", False)),
                cross_project_name=row.get("cross_project_name"),
            )
        )

    # --- resources and assignments ---------------------------------------
    resource_uid_by_ref: dict[str, UUID] = {}
    resources: list[Resource] = []
    for row in document.get("resources", []):
        uid = uid_for(EntityKind.RESOURCE, row)
        resource_uid_by_ref[str(row.get("id"))] = uid
        calendar_ref = row.get("calendar_ref")
        max_units = row.get("max_units")
        resource_type = _resource_type(row.get("source_resource_type"))
        resources.append(
            Resource(
                uid=uid,
                name=row.get("name") or "",
                code=row.get("initials"),
                type=resource_type,
                scheduling_class=SchedulingClass.NON_RENEWABLE
                if resource_type is ResourceType.COST
                else SchedulingClass.RENEWABLE,
                max_units_permille=None if max_units is None else _permille(max_units * 100),
                calendar_uid=calendar_uid_by_ref.get(str(calendar_ref)) if calendar_ref else None,
                group=row.get("group"),
                inactive=bool(row.get("inactive_source", False)),
                external_refs=(_ref(system, row, snapshot_sha),),
            )
        )

    assignments: list[Assignment] = []
    for row in document.get("assignments", []):
        uid = uid_for(EntityKind.ASSIGNMENT, row)
        task_ref = row.get("task_ref")
        resource_ref = row.get("resource_ref")
        units = row.get("units_source")
        work = _duration(row.get("work_source"))
        actual_work = _duration(row.get("actual_work_source"))
        remaining_work = _duration(row.get("remaining_work_source"))
        assignments.append(
            Assignment(
                uid=uid,
                activity_uid=node_uid.get(str(task_ref)) if task_ref else None,
                resource_uid=resource_uid_by_ref.get(str(resource_ref)) if resource_ref else None,
                units=UnitsTriple(
                    budgeted_permille=0 if units is None else _permille(units * 100)
                ),
                work=WorkTriple(
                    budgeted_seconds=0 if work is None else work.seconds,
                    actual_seconds=0 if actual_work is None else actual_work.seconds,
                    remaining_seconds=0 if remaining_work is None else remaining_work.seconds,
                ),
                start=_dt(row.get("start_source")),
                finish=_dt(row.get("finish_source")),
                percent_work_complete_permille=_permille(row.get("percent_work_complete_source")),
                unassigned_placeholder=resource_ref is None,
                external_refs=(_ref(system, row, snapshot_sha),),
            )
        )

    # --- baselines -------------------------------------------------------
    # Grouped by slot: Microsoft carries eleven, and each is a separate set of
    # captured activity states rather than a bag of key-value pairs.
    baseline_rows: dict[int, list[dict[str, Any]]] = {}
    for row in document.get("baselines", []):
        baseline_rows.setdefault(int(row.get("number") or 0), []).append(row)

    baselines: list[Baseline] = []
    for number, rows in sorted(baseline_rows.items()):
        states: list[BaselineActivityState] = []
        for row in rows:
            owner = node_uid.get(str(row.get("owner_ref")))
            if owner is None:
                continue
            values = row.get("values", {})
            duration = _duration(values.get("duration"))
            work = _duration(values.get("work"))
            states.append(
                BaselineActivityState(
                    activity_uid=owner,
                    start=_dt(values.get("start")),
                    finish=_dt(values.get("finish")),
                    duration_seconds=None if duration is None else duration.seconds,
                    work_seconds=None if work is None else work.seconds,
                )
            )
        baseline_uid, entry = identity.resolve(
            EntityKind.BASELINE, f"ms-baseline-{number}"
        )
        entries.append(entry)
        seen.setdefault(EntityKind.BASELINE, []).append(entry.external_uid)
        baselines.append(
            Baseline(
                uid=baseline_uid,
                name=f"Baseline {number}" if number else "Baseline",
                kind=BaselineKind.MS_BASELINE,
                number=number,
                source_snapshot_id=snapshot_id,
                activity_states=tuple(states),
            )
        )

    # --- project ---------------------------------------------------------
    default_calendar_ref = project_row.get("calendar_ref")
    project = ProjectSettings(
        name=project_row.get("title") or project_row.get("name") or "",
        start=_dt(project_row.get("start")),
        finish=_dt(project_row.get("finish")),
        status_date=_dt(project_row.get("status_date")),
        schedule_direction=ScheduleDirection.FROM_START
        if project_row.get("schedule_from_start", True)
        else ScheduleDirection.FROM_FINISH,
        progress_policy=ProgressPolicy.RETAINED_LOGIC,
        # Microsoft Project exposes no lag-calendar setting. Recording the
        # working assumption explicitly keeps it falsifiable rather than buried.
        lag_calendar_policy=LagCalendar.SUCCESSOR,
        milestone_snap_policy=MilestoneSnapPolicy.NONE,
        default_calendar_uid=calendar_uid_by_ref.get(str(default_calendar_ref))
        if default_calendar_ref
        else None,
        critical_float_threshold_seconds=_critical_threshold(project_row),
        minutes_per_day=project_row.get("minutes_per_day"),
        minutes_per_week=project_row.get("minutes_per_week"),
        days_per_month=project_row.get("days_per_month"),
    )

    snapshot = SourceSnapshot(
        snapshot_id=snapshot_id,
        system=system,
        format=SourceFormat.MSPDI,
        file_sha256=str(source.get("sha256") or ""),
        byte_length=int(source.get("byte_length") or 0),
        importer_profile=str(profile),
        document_name=source.get("document_name"),
        application="Microsoft Project",
        application_version=str(source.get("build_number"))
        if source.get("build_number") is not None
        else None,
        save_version=int(source["save_version"])
        if source.get("save_version") is not None
        else None,
        inventory={
            "wbs_nodes": len(wbs_nodes),
            "activities": len(activities),
            "relationships": len(relationships),
            "calendars": len(calendars),
            "resources": len(resources),
            "assignments": len(assignments),
        },
    )

    schedule = Schedule(
        schedule_id=resolved_id,
        project=project,
        snapshots=(snapshot,),
        wbs_nodes=tuple(wbs_nodes),
        activities=tuple(activities),
        relationships=tuple(relationships),
        calendars=tuple(calendars),
        resources=tuple(resources),
        assignments=tuple(assignments),
        udf_definitions=tuple(udf_definitions),
        baselines=tuple(baselines),
    )

    # Rows the identity map knows but this document did not carry. Iterate all
    # kinds the map knows, not only kinds seen in the current document, so
    # removing an entire collection is reported rather than disappearing.
    known_kinds = {
        EntityKind(kind_text) for kind_text, _ in identity.by_external.keys()
    }
    for kind in sorted(known_kinds | set(seen), key=str):
        entries.extend(identity.missing_since(kind, seen.get(kind, ())))

    return schedule, identity, ReconciliationReport(resolved_id, tuple(entries))
