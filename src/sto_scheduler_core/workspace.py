from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import os
import tempfile
from typing import Any

from .calculation_common import CalculationProfileError, _parse_datetime
from .calculation_profile import (
    PROFILE_VERSION,
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
)
from .mspdi import import_mspdi
from .provenance import canonical_sha256


WORKSPACE_SCHEMA_VERSION = "sto-local-schedule-workspace-v0.1"
MAX_DURATION_SECONDS = 365 * 24 * 60 * 60


class WorkspaceError(ValueError):
    """Base error for user-correctable local workspace operations."""


class WorkspaceNotLoadedError(WorkspaceError):
    pass


class ActivityNotEditableError(WorkspaceError):
    pass


class InvalidDurationError(WorkspaceError):
    pass


def _safe_display_name(value: str | None) -> str:
    candidate = (value or "schedule.xml").replace("\\", "/").split("/")[-1]
    candidate = "".join(character for character in candidate if character.isprintable())
    return candidate[:200] or "schedule.xml"


def _calculation_by_id(calculation: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if calculation is None:
        return {}
    return {item["id"]: item for item in calculation["activities"]}


def _ignored_calendar_ranges(
    document: dict[str, Any], profile: dict[str, Any] | None
) -> dict[str, tuple[tuple[datetime, datetime], ...]]:
    if profile is None:
        return {}
    calendars = {item["id"]: item for item in document["calendars"]}
    activities = {item["id"]: item for item in document["activities"]}
    resources = {item["id"]: item for item in document["resources"]}
    assignments_by_task: dict[str, list[dict[str, Any]]] = {}
    for assignment in document["assignments"]:
        assignments_by_task.setdefault(assignment.get("task_ref"), []).append(
            assignment
        )
    extensions = {
        item["id"]: item for item in document.get("vendor_extensions", [])
    }

    def calendar_lineage(calendar_ref: str | None) -> list[str]:
        lineage: list[str] = []
        visited: set[str] = set()
        while calendar_ref is not None and calendar_ref not in visited:
            visited.add(calendar_ref)
            lineage.append(calendar_ref)
            calendar_ref = calendars[calendar_ref].get("base_calendar_ref")
        return lineage

    result: dict[str, tuple[tuple[datetime, datetime], ...]] = {}
    for record in profile["activities"]:
        if (
            not record["eligible"]
            or activities[record["activity_id"]].get("milestone")
        ):
            continue
        activity = activities[record["activity_id"]]
        calendar_refs = set(record.get("calendar_source_lineage", []))
        ignore_resource_values = [
            extensions[extension_ref].get("payload", {}).get("text")
            for extension_ref in activity.get("extension_refs", [])
            if extensions[extension_ref].get("payload", {}).get("name")
            == "IgnoreResourceCalendar"
        ]
        ignores_resources = (
            activity.get("calendar_ref") is not None
            and ignore_resource_values == ["1"]
        )
        if not ignores_resources:
            for assignment in assignments_by_task.get(record["activity_id"], []):
                resource_ref = assignment.get("resource_ref")
                if resource_ref is None:
                    continue
                calendar_refs.update(
                    calendar_lineage(resources[resource_ref].get("calendar_ref"))
                )

        ranges: set[tuple[datetime, datetime]] = set()
        for calendar_ref in calendar_refs:
            calendar = calendars[calendar_ref]
            for exception in calendar.get("exceptions", []):
                ranges.add(
                    (
                        _parse_datetime(exception.get("from")),
                        _parse_datetime(exception.get("to")),
                    )
                )
            for special_day in calendar.get("week_days", []):
                if special_day.get("day_type") in range(1, 8):
                    continue
                periods = [
                    extension
                    for extension in special_day.get("extensions", [])
                    if extension.get("name") == "TimePeriod"
                ]
                children = {
                    child.get("name"): child.get("text")
                    for child in periods[0].get("children", [])
                }
                ranges.add(
                    (
                        _parse_datetime(children.get("FromDate")),
                        _parse_datetime(children.get("ToDate")),
                    )
                )
        if ranges:
            result[record["activity_id"]] = tuple(sorted(ranges))
    return result


def _calculation_windows(
    projection: dict[str, Any],
    calculation: dict[str, Any],
) -> dict[str, tuple[datetime, datetime]]:
    project_start = _parse_datetime(projection["project"].get("start"))
    projected_by_id = {
        item["id"]: item for item in projection["activities"]
    }
    calculated_by_id = _calculation_by_id(calculation)
    predecessors: dict[str, list[dict[str, Any]]] = {}
    for relationship in projection["relationships"]:
        predecessors.setdefault(relationship["successor_ref"], []).append(
            relationship
        )

    windows: dict[str, tuple[datetime, datetime]] = {}
    for activity_id, activity in projected_by_id.items():
        if activity["milestone"]:
            continue
        candidates = [
            _parse_datetime(
                calculated_by_id[relationship["predecessor_ref"]].get(
                    "calculated_finish"
                )
            )
            + timedelta(seconds=relationship["lag_seconds"])
            for relationship in predecessors.get(activity_id, [])
        ]
        candidate = max(candidates) if candidates else project_start
        finish = _parse_datetime(
            calculated_by_id[activity_id].get("calculated_finish")
        )
        windows[activity_id] = (candidate, finish)
    return windows


def _validate_calculation_calendar_horizon(
    projection: dict[str, Any],
    calculation: dict[str, Any],
    ignored_ranges: dict[str, tuple[tuple[datetime, datetime], ...]],
    *,
    error_type: type[ValueError],
) -> None:
    if not ignored_ranges:
        return
    windows = _calculation_windows(projection, calculation)
    for activity_id, ranges in ignored_ranges.items():
        candidate, finish = windows[activity_id]
        if any(
            blocked_start <= finish and candidate <= blocked_finish
            for blocked_start, blocked_finish in ranges
        ):
            raise error_type(
                "A calculated activity crosses a calendar exception or special "
                "day outside the imported calculation horizon"
            )


class ScheduleWorkspace:
    """In-memory state for the Prototype 0 local scenario workspace.

    The imported canonical document remains unchanged. Scenario recalculation starts
    from the frozen engine projection and changes only explicitly selected durations.
    """

    def __init__(self) -> None:
        self._document: dict[str, Any] | None = None
        self._profile: dict[str, Any] | None = None
        self._base_projection: dict[str, Any] | None = None
        self._base_calculation: dict[str, Any] | None = None
        self._current_calculation: dict[str, Any] | None = None
        self._duration_overrides: dict[str, int] = {}
        self._display_name: str | None = None
        self._calculation_error: str | None = None
        self._ignored_calendar_ranges: dict[
            str, tuple[tuple[datetime, datetime], ...]
        ] = {}
        self._revision = 0

    @property
    def loaded(self) -> bool:
        return self._document is not None

    def load_mspdi(
        self, path: str | Path, *, display_name: str | None = None
    ) -> dict[str, Any]:
        source_path = Path(path)
        document = import_mspdi(source_path)
        return self.load_document(
            document, display_name=display_name or source_path.name
        )

    def load_mspdi_bytes(
        self, payload: bytes, *, display_name: str | None = None
    ) -> dict[str, Any]:
        if not payload:
            raise WorkspaceError("The selected XML file is empty")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="sto-workspace-", suffix=".xml"
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            temporary_path.write_bytes(payload)
            return self.load_mspdi(
                temporary_path, display_name=_safe_display_name(display_name)
            )
        finally:
            temporary_path.unlink(missing_ok=True)

    def load_document(
        self, document: dict[str, Any], *, display_name: str = "schedule.xml"
    ) -> dict[str, Any]:
        profile: dict[str, Any] | None = None
        projection: dict[str, Any] | None = None
        calculation: dict[str, Any] | None = None
        calculation_error: str | None = None
        ignored_ranges: dict[
            str, tuple[tuple[datetime, datetime], ...]
        ] = {}
        try:
            profile = build_calculation_profile(document)
            ignored_ranges = _ignored_calendar_ranges(document, profile)
            projection = build_engine_projection(document, profile)
            calculation = calculate_forward_schedule(projection)
            _validate_calculation_calendar_horizon(
                projection,
                calculation,
                ignored_ranges,
                error_type=CalculationProfileError,
            )
        except (CalculationProfileError, ValueError) as exc:
            calculation = None
            calculation_error = str(exc)

        self._document = document
        self._profile = profile
        self._base_projection = projection
        self._base_calculation = calculation
        self._current_calculation = calculation
        self._duration_overrides = {}
        self._display_name = _safe_display_name(display_name)
        self._calculation_error = calculation_error
        self._ignored_calendar_ranges = ignored_ranges
        self._revision = 0
        return self.snapshot()

    def recalculate_duration(
        self,
        activity_id: str,
        duration_seconds: int,
        *,
        document_key: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        if (
            self._base_projection is None
            or self._profile is None
            or self._base_calculation is None
        ):
            if self._document is None:
                raise WorkspaceNotLoadedError("Import an MSPDI XML schedule first")
            raise ActivityNotEditableError(
                "This schedule is outside the current calculation profile"
            )
        expected_document_key = self._document["source"]["document_key"]
        if document_key is not None and document_key != expected_document_key:
            raise ActivityNotEditableError(
                "The requested task belongs to a different imported schedule"
            )
        if revision is not None and revision != self._revision:
            raise ActivityNotEditableError(
                "The scenario changed in another workspace tab; reload before retrying"
            )
        if type(duration_seconds) is not int:
            raise InvalidDurationError("Duration must be an integer number of seconds")
        if not 1 <= duration_seconds <= MAX_DURATION_SECONDS:
            raise InvalidDurationError(
                "Duration must be greater than zero and no more than 8,760 hours"
            )

        projection_activity = next(
            (
                item
                for item in self._base_projection["activities"]
                if item["id"] == activity_id
            ),
            None,
        )
        if projection_activity is None:
            raise ActivityNotEditableError(
                "Only activities admitted by the current calculation profile "
                "can be changed"
            )
        if projection_activity["milestone"]:
            raise ActivityNotEditableError("Milestone durations cannot be changed")

        original_seconds = projection_activity["duration_seconds"]
        proposed_overrides = dict(self._duration_overrides)
        if duration_seconds == original_seconds:
            proposed_overrides.pop(activity_id, None)
        else:
            proposed_overrides[activity_id] = duration_seconds

        scenario_projection = deepcopy(self._base_projection)
        for activity in scenario_projection["activities"]:
            override = proposed_overrides.get(activity["id"])
            if override is not None:
                activity["duration_seconds"] = override
        proposed_calculation = calculate_forward_schedule(scenario_projection)
        _validate_calculation_calendar_horizon(
            scenario_projection,
            proposed_calculation,
            self._ignored_calendar_ranges,
            error_type=InvalidDurationError,
        )
        self._duration_overrides = proposed_overrides
        self._current_calculation = proposed_calculation
        self._revision += 1
        return self.snapshot()

    def reset(
        self,
        *,
        document_key: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        if self._document is None:
            raise WorkspaceNotLoadedError("Import an MSPDI XML schedule first")
        expected_document_key = self._document["source"]["document_key"]
        if document_key is not None and document_key != expected_document_key:
            raise ActivityNotEditableError(
                "The reset request belongs to a different imported schedule"
            )
        if revision is not None and revision != self._revision:
            raise ActivityNotEditableError(
                "The scenario changed in another workspace tab; reload before retrying"
            )
        self._duration_overrides = {}
        self._current_calculation = self._base_calculation
        self._revision += 1
        return self.snapshot()

    def _rows(self) -> list[dict[str, Any]]:
        if self._document is None:
            return []
        document = self._document
        profile_by_id = {
            item["activity_id"]: item
            for item in (self._profile or {}).get("activities", [])
        }
        base_by_id = _calculation_by_id(self._base_calculation)
        current_by_id = _calculation_by_id(self._current_calculation)
        projection_by_id = {
            item["id"]: item
            for item in (self._base_projection or {}).get("activities", [])
        }
        successor_ids = {
            item["predecessor_ref"]
            for item in (self._base_projection or {}).get("relationships", [])
        }

        rows: list[dict[str, Any]] = []
        for item in document["wbs_nodes"]:
            rows.append(
                {
                    "id": item["id"],
                    "kind": "summary",
                    "parent_id": item.get("parent_id"),
                    "source_order": item["source_order"],
                    "outline_level": item.get("outline_level"),
                    "outline_number": item.get("outline_number"),
                    "wbs": item.get("wbs"),
                    "name": item.get("name") or "Untitled summary",
                    "milestone": bool(item.get("milestone_source")),
                    "imported_start": item.get("start"),
                    "imported_finish": item.get("finish"),
                    "calculated_start": None,
                    "calculated_finish": None,
                    "base_calculated_start": None,
                    "base_calculated_finish": None,
                    "imported_duration_seconds": (item.get("duration") or {}).get(
                        "seconds"
                    ),
                    "scenario_duration_seconds": None,
                    "supported": False,
                    "editable": False,
                    "has_supported_successor": False,
                    "primary_reason": "SUMMARY_TASK",
                    "reason_codes": ["SUMMARY_TASK"],
                    "scenario_changed": False,
                    "moved": False,
                    "impact": None,
                    "start_delta_seconds": None,
                    "finish_delta_seconds": None,
                }
            )

        for item in document["activities"]:
            activity_id = item["id"]
            profile_record = profile_by_id.get(activity_id)
            base = base_by_id.get(activity_id)
            current = current_by_id.get(activity_id)
            projected = projection_by_id.get(activity_id)
            profile_eligible = bool(
                profile_record and profile_record.get("eligible")
            )
            supported = profile_eligible and self._base_calculation is not None
            changed = activity_id in self._duration_overrides
            moved = bool(base and current and base != current)
            start_delta = None
            finish_delta = None
            if base and current:
                start_delta = int(
                    (
                        datetime.fromisoformat(current["calculated_start"])
                        - datetime.fromisoformat(base["calculated_start"])
                    ).total_seconds()
                )
                finish_delta = int(
                    (
                        datetime.fromisoformat(current["calculated_finish"])
                        - datetime.fromisoformat(base["calculated_finish"])
                    ).total_seconds()
                )
            if profile_record and not profile_eligible:
                reason_codes = list(profile_record.get("reason_codes", []))
                primary_reason = profile_record.get("primary_reason")
            elif profile_eligible and not supported:
                reason_codes = ["CALCULATION_UNAVAILABLE"]
                primary_reason = "CALCULATION_UNAVAILABLE"
            elif profile_record:
                reason_codes = []
                primary_reason = None
            else:
                reason_codes = ["CALCULATION_PROFILE_UNAVAILABLE"]
                primary_reason = "CALCULATION_PROFILE_UNAVAILABLE"
            imported_duration = (item.get("duration") or {}).get("seconds")
            scenario_duration = (
                self._duration_overrides.get(activity_id)
                if changed
                else (
                    projected.get("duration_seconds")
                    if projected
                    else imported_duration
                )
            )
            rows.append(
                {
                    "id": activity_id,
                    "kind": "activity",
                    "parent_id": item.get("parent_wbs_id"),
                    "source_order": item["source_order"],
                    "outline_level": item.get("outline_level"),
                    "outline_number": item.get("outline_number"),
                    "wbs": item.get("wbs"),
                    "name": item.get("name") or "Untitled activity",
                    "milestone": bool(item.get("milestone")),
                    "imported_start": item.get("start"),
                    "imported_finish": item.get("finish"),
                    "calculated_start": (
                        current.get("calculated_start") if current else None
                    ),
                    "calculated_finish": (
                        current.get("calculated_finish") if current else None
                    ),
                    "base_calculated_start": (
                        base.get("calculated_start") if base else None
                    ),
                    "base_calculated_finish": (
                        base.get("calculated_finish") if base else None
                    ),
                    "imported_duration_seconds": imported_duration,
                    "scenario_duration_seconds": scenario_duration,
                    "supported": supported,
                    "editable": supported and not bool(item.get("milestone")),
                    "has_supported_successor": activity_id in successor_ids,
                    "primary_reason": primary_reason,
                    "reason_codes": reason_codes,
                    "scenario_changed": changed,
                    "moved": moved,
                    "impact": "edited" if changed else "downstream" if moved else None,
                    "start_delta_seconds": start_delta,
                    "finish_delta_seconds": finish_delta,
                }
            )
        return sorted(rows, key=lambda item: (item["source_order"], item["id"]))

    def snapshot(self) -> dict[str, Any]:
        if self._document is None:
            return {
                "workspace_schema_version": WORKSPACE_SCHEMA_VERSION,
                "loaded": False,
                "calculation_profile": PROFILE_VERSION,
                "limits": {"maximum_duration_seconds": MAX_DURATION_SECONDS},
            }

        document = self._document
        rows = self._rows()
        moved_count = sum(1 for row in rows if row["moved"])
        downstream_moved_count = sum(
            1 for row in rows if row["impact"] == "downstream"
        )
        profile_counts = (self._profile or {}).get(
            "counts",
            {
                "activities": len(document["activities"]),
                "eligible_activities": 0,
                "excluded_activities": len(document["activities"]),
                "eligible_relationships": 0,
            },
        )
        supported_activities = (
            profile_counts["eligible_activities"]
            if self._base_calculation is not None
            else 0
        )
        return {
            "workspace_schema_version": WORKSPACE_SCHEMA_VERSION,
            "loaded": True,
            "limits": {"maximum_duration_seconds": MAX_DURATION_SECONDS},
            "display_name": self._display_name,
            "source": {
                "format": document["source"]["format"],
                "sha256": document["source"]["sha256"],
                "document_key": document["source"]["document_key"],
                "byte_length": document["source"]["byte_length"],
                "importer_profile": document["importer_profile"],
                "canonical_schema_version": document["schema_version"],
                "canonical_sha256": (
                    (self._profile or {}).get("source", {}).get("canonical_sha256")
                    or canonical_sha256(document)
                ),
            },
            "project": {
                "name": document["project"].get("name")
                or document["project"].get("title")
                or self._display_name,
                "imported_start": document["project"].get("start"),
                "imported_finish": document["project"].get("finish"),
                "status_date": document["project"].get("status_date"),
            },
            "counts": {
                "tasks": document["source_inventory"]["tasks"],
                "summary_tasks": document["source_inventory"]["summary_tasks"],
                "activities": len(document["activities"]),
                "relationships": document["source_inventory"]["relationships"],
                "supported_activities": supported_activities,
                "unsupported_activities": len(document["activities"])
                - supported_activities,
                "supported_relationships": profile_counts.get(
                    "eligible_relationships", 0
                )
                if self._base_calculation is not None
                else 0,
            },
            "calculation": {
                "profile": PROFILE_VERSION,
                "available": self._current_calculation is not None,
                "error": self._calculation_error,
                "scope": "eligible-activities-only",
                "claim_boundary": (
                    "Engine-native forward dates for the admitted subset only; "
                    "not Microsoft Project recalculation or compatibility evidence."
                ),
            },
            "scenario": {
                "revision": self._revision,
                "changed": bool(self._duration_overrides),
                "duration_overrides": [
                    {
                        "activity_id": activity_id,
                        "imported_duration_seconds": next(
                            item["duration_seconds"]
                            for item in self._base_projection["activities"]
                            if item["id"] == activity_id
                        ),
                        "duration_seconds": duration_seconds,
                    }
                    for activity_id, duration_seconds in sorted(
                        self._duration_overrides.items()
                    )
                ],
                "moved_activity_count": moved_count,
                "downstream_moved_activity_count": downstream_moved_count,
                "base_projection_sha256": canonical_sha256(self._base_projection)
                if self._base_projection is not None
                else None,
                "base_calculation_sha256": canonical_sha256(
                    self._base_calculation
                )
                if self._base_calculation is not None
                else None,
                "current_calculation_sha256": canonical_sha256(
                    self._current_calculation
                )
                if self._current_calculation is not None
                else None,
            },
            "tasks": rows,
            "native_project_validation": "not_executed",
        }

    def export_state(self) -> dict[str, Any]:
        if self._document is None:
            raise WorkspaceNotLoadedError("Import an MSPDI XML schedule first")
        return {
            "export_type": "prototype-0-local-schedule-workspace-state",
            **self.snapshot(),
        }
