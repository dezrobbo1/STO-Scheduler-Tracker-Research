"""Prototype 0 local schedule workspace domain layer.

The imported canonical document is a source snapshot. Scenario edits are kept
separate and are applied only to a copy of the engine projection so imported
coordinates and calculation eligibility remain unchanged.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

from .calculation_calendar import calculation_source_horizon
from .calculation_common import CalculationProfileError, _parse_datetime
from .calculation_profile import (
    build_calculation_profile,
    build_engine_projection,
    calculate_forward_schedule,
)
from .mspdi import import_mspdi
from .provenance import canonical_sha256


WORKSPACE_PROFILE = "prototype-0-local-schedule-workspace-v0.1"
WORKSPACE_EXPORT_PROFILE = "prototype-0-local-schedule-workspace-export-v0.1"

_INVENTORY_KEYS = (
    "tasks",
    "summary_tasks",
    "leaf_activities",
    "milestones",
    "activity_milestones",
    "summary_milestones",
    "relationships",
    "relationship_types",
    "calendars",
    "resources",
    "assignments",
    "baselines",
    "custom_field_definitions",
    "vendor_extensions",
)


def _selected_fields(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: deepcopy(source.get(key)) for key in keys}


def _workspace_document_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    """Copy only the imported facts exposed by the compact workspace.

    Real MSPDI files can retain hundreds of thousands of vendor-extension
    records. Copying the full canonical document would roughly double that
    memory, while retaining the caller's mutable object would make cached
    provenance and later views disagree. This snapshot provides isolation
    without retaining extension, resource, assignment, or calendar payloads.
    """

    project_keys = (
        "id",
        "name",
        "title",
        "start",
        "finish",
        "status_date",
        "calendar_ref",
    )
    wbs_keys = (
        "id",
        "parent_id",
        "source_order",
        "source_uid",
        "name",
        "wbs",
        "outline_number",
        "outline_level",
        "start",
        "finish",
        "duration",
    )
    activity_keys = (
        "id",
        "parent_wbs_id",
        "source_order",
        "source_uid",
        "name",
        "wbs",
        "outline_number",
        "outline_level",
        "milestone",
        "start",
        "finish",
        "duration",
    )
    relationship_keys = (
        "id",
        "source_order",
        "predecessor_ref",
        "successor_ref",
        "type",
        "lag_seconds",
    )
    return {
        "schema_version": document["schema_version"],
        "importer_profile": document["importer_profile"],
        "source": deepcopy(document["source"]),
        "project": _selected_fields(document["project"], project_keys),
        "source_inventory": _selected_fields(
            document["source_inventory"], _INVENTORY_KEYS
        ),
        "wbs_nodes": [
            _selected_fields(item, wbs_keys) for item in document["wbs_nodes"]
        ],
        "activities": [
            _selected_fields(item, activity_keys)
            for item in document["activities"]
        ],
        "relationships": [
            _selected_fields(item, relationship_keys)
            for item in document["relationships"]
        ],
    }


class WorkspaceScenarioError(ValueError):
    """A machine-readable rejection at the workspace scenario boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        activity_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.activity_id = activity_id
        self.details = deepcopy(details) if details is not None else {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "activity_id": self.activity_id,
            "details": deepcopy(self.details),
        }


def _calculation_by_id(calculation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in calculation["activities"]}


def _projection_activity_by_id(
    projection: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in projection["activities"]}


def _coordinate_delta_seconds(current: str, base: str) -> int:
    return int((_parse_datetime(current) - _parse_datetime(base)).total_seconds())


def _eligible_downstream_counts(projection: dict[str, Any]) -> dict[str, int]:
    """Count unique reachable successors with compact DAG bit sets."""

    activity_ids = [activity["id"] for activity in projection["activities"]]
    index_by_id = {
        activity_id: index for index, activity_id in enumerate(activity_ids)
    }
    adjacency: list[list[int]] = [[] for _ in activity_ids]
    indegree = [0 for _ in activity_ids]
    for relationship in projection["relationships"]:
        predecessor = index_by_id[relationship["predecessor_ref"]]
        successor = index_by_id[relationship["successor_ref"]]
        adjacency[predecessor].append(successor)
        indegree[successor] += 1

    ready = deque(index for index, degree in enumerate(indegree) if degree == 0)
    topological_order: list[int] = []
    while ready:
        predecessor = ready.popleft()
        topological_order.append(predecessor)
        for successor in adjacency[predecessor]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
    if len(topological_order) != len(activity_ids):
        # Successful forward calculation already guarantees a DAG. Keep this
        # guard local so the helper never loops or reports misleading counts.
        raise CalculationProfileError(
            "Workspace projection contains a relationship cycle"
        )

    reachable = [0 for _ in activity_ids]
    for predecessor in reversed(topological_order):
        successors = 0
        for successor in adjacency[predecessor]:
            successors |= (1 << successor) | reachable[successor]
        reachable[predecessor] = successors
    return {
        activity_id: reachable[index].bit_count()
        for index, activity_id in enumerate(activity_ids)
    }


class WorkspaceSession:
    """One local imported schedule and at most one active duration scenario."""

    __slots__ = (
        "_document",
        "_profile",
        "_base_projection",
        "_base_calculation",
        "_current_projection",
        "_current_calculation",
        "_duration_override",
        "_profile_by_activity",
        "_activity_by_id",
        "_wbs_by_id",
        "_base_projection_activity_by_id",
        "_downstream_counts",
        "_recommended_editable_task",
        "_horizon_start",
        "_horizon_finish",
        "_canonical_sha256",
        "_base_projection_sha256",
        "_base_calculation_sha256",
        "_workspace_id",
        "_source_filename",
        "_revision",
    )

    def __init__(
        self,
        document: dict[str, Any],
        profile: dict[str, Any],
        projection: dict[str, Any],
        calculation: dict[str, Any],
        source_filename: str | None,
    ) -> None:
        # Hash the complete canonical document before retaining only the compact
        # facts required by this workspace. All scenario calculations start
        # from a fresh copy of the base projection.
        self._canonical_sha256 = canonical_sha256(document)
        self._horizon_start, self._horizon_finish = calculation_source_horizon(
            document
        )
        self._document = _workspace_document_snapshot(document)
        self._profile = profile
        self._base_projection = projection
        self._base_calculation = calculation
        self._current_projection = projection
        self._current_calculation = calculation
        self._duration_override: dict[str, Any] | None = None
        source = self._document["source"]
        self._workspace_id = f"workspace:{source['sha256']}"
        self._source_filename = source_filename or source.get("document_name")
        self._revision = 0

        self._profile_by_activity = {
            item["activity_id"]: item for item in profile["activities"]
        }
        self._activity_by_id = {
            item["id"]: item for item in self._document["activities"]
        }
        self._wbs_by_id = {
            item["id"]: item for item in self._document["wbs_nodes"]
        }
        self._base_projection_activity_by_id = _projection_activity_by_id(
            projection
        )
        self._downstream_counts = _eligible_downstream_counts(projection)
        self._base_projection_sha256 = canonical_sha256(projection)
        self._base_calculation_sha256 = canonical_sha256(calculation)
        self._recommended_editable_task = self._choose_recommended_editable_task()

    @classmethod
    def from_document(
        cls, document: dict[str, Any], source_filename: str | None = None
    ) -> "WorkspaceSession":
        if not isinstance(document, dict):
            raise TypeError("Canonical document must be an object")
        # Consume the complete canonical document for eligibility and projection.
        # The constructor then retains an isolated compact source snapshot, while
        # scenario work copies only the compact engine projection.
        profile = build_calculation_profile(document)
        projection = build_engine_projection(document, profile)
        calculation = calculate_forward_schedule(projection)
        return cls(document, profile, projection, calculation, source_filename)

    @classmethod
    def from_mspdi(cls, path: str | Path) -> "WorkspaceSession":
        source_path = Path(path)
        return cls.from_document(import_mspdi(source_path), source_path.name)

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def revision(self) -> int:
        return self._revision

    def _choose_recommended_editable_task(self) -> dict[str, Any] | None:
        editable = [
            activity
            for activity in self._base_projection["activities"]
            if not activity["milestone"]
        ]
        if not editable:
            return None
        selected = min(
            editable,
            key=lambda item: (
                -self._downstream_counts[item["id"]],
                item["source_order"],
                item["id"],
            ),
        )
        imported = self._activity_by_id[selected["id"]]
        return {
            "activity_id": selected["id"],
            "name": imported.get("name"),
            "eligible_downstream_count": self._downstream_counts[selected["id"]],
        }

    def _source_provenance(self) -> dict[str, Any]:
        source = self._document["source"]
        return {
            "system": source.get("system"),
            "format": source.get("format"),
            "namespace": source.get("namespace"),
            "sha256": source.get("sha256"),
            "byte_length": source.get("byte_length"),
            "document_name": source.get("document_name"),
            "file_name": self._source_filename,
            "identity_scope": source.get("identity_scope"),
            "document_key": source.get("document_key"),
            "durable_cross_snapshot_identity": source.get(
                "durable_cross_snapshot_identity"
            ),
            "schema_version": self._document["schema_version"],
            "importer_profile": self._document["importer_profile"],
            "canonical_sha256": self._canonical_sha256,
        }

    def _scenario_summary(self, moved_task_count: int) -> dict[str, Any]:
        return {
            "active": self._duration_override is not None,
            "moved_task_count": moved_task_count,
            "duration_override": deepcopy(self._duration_override),
            "base_projection_sha256": self._base_projection_sha256,
            "current_projection_sha256": canonical_sha256(
                self._current_projection
            ),
            "base_calculation_sha256": self._base_calculation_sha256,
            "current_calculation_sha256": canonical_sha256(
                self._current_calculation
            ),
        }

    def _safe_horizon_violations(
        self, calculation: dict[str, Any]
    ) -> list[dict[str, Any]]:
        base_by_id = _calculation_by_id(self._base_calculation)
        violations: list[dict[str, Any]] = []
        for current in calculation["activities"]:
            activity_id = current["id"]
            base = base_by_id[activity_id]
            if (
                current["calculated_start"] == base["calculated_start"]
                and current["calculated_finish"] == base["calculated_finish"]
            ):
                continue
            profile = self._profile_by_activity[activity_id]
            if profile.get("ignored_nonoverlapping_exception_count", 0) <= 0:
                continue
            start = _parse_datetime(current["calculated_start"])
            finish = _parse_datetime(current["calculated_finish"])
            if start < self._horizon_start or finish > self._horizon_finish:
                violations.append(
                    {
                        "activity_id": activity_id,
                        "calculated_start": current["calculated_start"],
                        "calculated_finish": current["calculated_finish"],
                        "ignored_nonoverlapping_exception_count": profile[
                            "ignored_nonoverlapping_exception_count"
                        ],
                    }
                )
        return violations

    def set_duration(
        self, activity_id: str, duration_seconds: int
    ) -> dict[str, Any]:
        """Apply one duration override and return the resulting compact view."""

        if not isinstance(activity_id, str) or not activity_id:
            raise WorkspaceScenarioError(
                "ACTIVITY_ID_INVALID",
                "Activity id must be a non-empty string",
            )
        if type(duration_seconds) is not int or duration_seconds <= 0:
            raise WorkspaceScenarioError(
                "DURATION_INVALID",
                "Duration must be a positive integral number of seconds",
                activity_id=activity_id,
                details={"duration_seconds": duration_seconds},
            )
        if activity_id in self._wbs_by_id:
            raise WorkspaceScenarioError(
                "SUMMARY_TASK_UNSUPPORTED",
                "Summary-task duration overrides are not supported",
                activity_id=activity_id,
            )
        profile = self._profile_by_activity.get(activity_id)
        if profile is None:
            raise WorkspaceScenarioError(
                "ACTIVITY_NOT_FOUND",
                "Activity does not exist in this imported document",
                activity_id=activity_id,
            )
        if not profile["eligible"]:
            raise WorkspaceScenarioError(
                "ACTIVITY_INELIGIBLE",
                "Activity is outside the current calculation profile",
                activity_id=activity_id,
                details={"reason_codes": list(profile["reason_codes"])},
            )
        base_activity = self._base_projection_activity_by_id[activity_id]
        if base_activity["milestone"]:
            raise WorkspaceScenarioError(
                "MILESTONE_UNSUPPORTED",
                "Milestone duration overrides are not supported",
                activity_id=activity_id,
            )

        candidate_projection = deepcopy(self._base_projection)
        candidate_activity = _projection_activity_by_id(candidate_projection)[
            activity_id
        ]
        candidate_activity["duration_seconds"] = duration_seconds
        try:
            candidate_calculation = calculate_forward_schedule(candidate_projection)
        except CalculationProfileError as exc:
            raise WorkspaceScenarioError(
                "SCENARIO_CALCULATION_FAILED",
                f"Scenario calculation failed: {exc}",
                activity_id=activity_id,
            ) from exc

        violations = self._safe_horizon_violations(candidate_calculation)
        if violations:
            raise WorkspaceScenarioError(
                "SCENARIO_OUTSIDE_SAFE_HORIZON",
                (
                    "Scenario moves activities with ignored calendar exceptions "
                    "outside the original calculation horizon"
                ),
                activity_id=activity_id,
                details={
                    "safe_horizon": {
                        "start": self._horizon_start.isoformat(),
                        "finish": self._horizon_finish.isoformat(),
                    },
                    "violations": violations,
                },
            )

        self._current_projection = candidate_projection
        self._current_calculation = candidate_calculation
        self._duration_override = {
            "activity_id": activity_id,
            "original_duration_seconds": base_activity["duration_seconds"],
            "duration_seconds": duration_seconds,
            "delta_seconds": duration_seconds - base_activity["duration_seconds"],
        }
        self._revision += 1
        return self.view()

    def reset(self) -> dict[str, Any]:
        """Discard the active scenario and restore the exact base calculation."""

        if self._duration_override is not None:
            self._current_projection = self._base_projection
            self._current_calculation = self._base_calculation
            self._duration_override = None
            self._revision += 1
        return self.view()

    def _task_rows(self) -> list[dict[str, Any]]:
        base_calculation_by_id = _calculation_by_id(self._base_calculation)
        current_calculation_by_id = _calculation_by_id(self._current_calculation)
        current_projection_by_id = _projection_activity_by_id(
            self._current_projection
        )
        override_id = (
            self._duration_override["activity_id"]
            if self._duration_override is not None
            else None
        )

        combined = [
            ("summary", item) for item in self._document["wbs_nodes"]
        ] + [("activity", item) for item in self._document["activities"]]
        combined.sort(key=lambda item: (item[1]["source_order"], item[1]["id"]))

        rows = []
        for kind, source in combined:
            activity_id = source["id"]
            profile = self._profile_by_activity.get(activity_id)
            calculation_supported = bool(profile and profile["eligible"])
            milestone = bool(source.get("milestone")) if kind == "activity" else False
            duration_editable = calculation_supported and not milestone
            if kind == "summary":
                support_reasons = ["SUMMARY_TASK_NOT_CALCULATED"]
                edit_reasons = ["SUMMARY_TASK_DURATION_OVERRIDE_UNSUPPORTED"]
            elif not calculation_supported:
                support_reasons = list(profile["reason_codes"]) if profile else []
                edit_reasons = list(support_reasons)
            elif milestone:
                support_reasons = []
                edit_reasons = ["MILESTONE_DURATION_OVERRIDE_UNSUPPORTED"]
            else:
                support_reasons = []
                edit_reasons = []

            base = base_calculation_by_id.get(activity_id)
            current = current_calculation_by_id.get(activity_id)
            if base is not None and current is not None:
                start_delta = _coordinate_delta_seconds(
                    current["calculated_start"], base["calculated_start"]
                )
                finish_delta = _coordinate_delta_seconds(
                    current["calculated_finish"], base["calculated_finish"]
                )
            else:
                start_delta = finish_delta = None
            duration = source.get("duration") or {}
            projected = current_projection_by_id.get(activity_id)
            rows.append(
                {
                    "id": activity_id,
                    "kind": kind,
                    "parent_id": source.get("parent_id")
                    if kind == "summary"
                    else source.get("parent_wbs_id"),
                    "source_order": source["source_order"],
                    "source_uid": source.get("source_uid"),
                    "name": source.get("name"),
                    "wbs": source.get("wbs"),
                    "outline_number": source.get("outline_number"),
                    "outline_level": source.get("outline_level"),
                    "milestone": milestone,
                    "supported": calculation_supported,
                    "duration_editable": duration_editable,
                    "support_reasons": support_reasons,
                    "duration_edit_reasons": edit_reasons,
                    "downstream_count": self._downstream_counts.get(activity_id),
                    "duration": {
                        "imported_raw": duration.get("raw"),
                        "imported_seconds": duration.get("seconds"),
                        "current_seconds": projected.get("duration_seconds")
                        if projected is not None
                        else duration.get("seconds"),
                        "overridden": activity_id == override_id,
                    },
                    "imported": {
                        "start": source.get("start"),
                        "finish": source.get("finish"),
                    },
                    "calculated": {
                        "base_start": base.get("calculated_start")
                        if base
                        else None,
                        "base_finish": base.get("calculated_finish")
                        if base
                        else None,
                        "current_start": current.get("calculated_start")
                        if current
                        else None,
                        "current_finish": current.get("calculated_finish")
                        if current
                        else None,
                        "changed": start_delta not in (None, 0)
                        or finish_delta not in (None, 0),
                        "start_delta_seconds": start_delta,
                        "finish_delta_seconds": finish_delta,
                    },
                }
            )
        return rows

    def view(self) -> dict[str, Any]:
        rows = self._task_rows()
        changed_count = sum(
            bool(row["calculated"]["changed"]) for row in rows
        )
        editable_count = sum(bool(row["duration_editable"]) for row in rows)
        calculated_count = sum(bool(row["supported"]) for row in rows)
        project = self._document["project"]
        inventory = {
            key: deepcopy(self._document["source_inventory"].get(key))
            for key in _INVENTORY_KEYS
        }
        recommended_task_id = (
            self._recommended_editable_task["activity_id"]
            if self._recommended_editable_task is not None
            else None
        )
        return {
            "workspace_profile": WORKSPACE_PROFILE,
            "workspace_id": self._workspace_id,
            "revision": self._revision,
            "source": self._source_provenance(),
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
                "title": project.get("title"),
                "start": project.get("start"),
                "finish": project.get("finish"),
                "status_date": project.get("status_date"),
                "calendar_ref": project.get("calendar_ref"),
            },
            "inventory": inventory,
            "calculation": {
                "profile": self._profile["profile"],
                **deepcopy(self._profile["counts"]),
            },
            "counts": {
                "tasks": len(rows),
                "summary_tasks": len(self._document["wbs_nodes"]),
                "activities": len(self._document["activities"]),
                "calculated_activities": calculated_count,
                "editable_activities": editable_count,
                "changed_activities": changed_count,
            },
            "safe_scenario_horizon": {
                "start": self._horizon_start.isoformat(),
                "finish": self._horizon_finish.isoformat(),
            },
            "recommended_editable_task": deepcopy(
                self._recommended_editable_task
            ),
            "recommended_task_id": recommended_task_id,
            "scenario": self._scenario_summary(changed_count),
            "tasks": rows,
        }

    def export_state(self) -> dict[str, Any]:
        """Return a deterministic, compact JSON-ready prototype state envelope."""

        exported = self.view()
        exported["export_profile"] = WORKSPACE_EXPORT_PROFILE
        exported["workspace_schema_version"] = "0.1.0"
        exported["duration_overrides_seconds"] = (
            {
                self._duration_override["activity_id"]: self._duration_override[
                    "duration_seconds"
                ]
            }
            if self._duration_override is not None
            else {}
        )
        eligible_relationship_ids = set(self._profile["eligible_relationship_ids"])
        exported["relationships"] = [
            {
                "id": relationship["id"],
                "source_order": relationship["source_order"],
                "predecessor_ref": relationship.get("predecessor_ref"),
                "successor_ref": relationship.get("successor_ref"),
                "type": relationship.get("type"),
                "lag_seconds": relationship.get("lag_seconds"),
                "calculation_supported": relationship["id"]
                in eligible_relationship_ids,
            }
            for relationship in sorted(
                self._document["relationships"],
                key=lambda item: (item["source_order"], item["id"]),
            )
        ]
        return exported
