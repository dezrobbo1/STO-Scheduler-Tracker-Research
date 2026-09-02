from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any

from .calculation_calendar import _add_working_seconds, _next_working_time
from .calculation_common import (
    CalculationProfileError,
    PROFILE_VERSION,
    _is_integral_seconds,
    _parse_datetime,
)
from .provenance import canonical_sha256


def _expected_calculation_source(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": document["schema_version"],
        "importer_profile": document["importer_profile"],
        "source_sha256": document["source"]["sha256"],
        "document_key": document["source"]["document_key"],
        "canonical_sha256": canonical_sha256(document),
    }


def _require_rows(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CalculationProfileError(f"Projection {label} must be a list")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise CalculationProfileError(
                f"Projection {label}[{index}] must be an object"
            )
        rows.append(item)
    return rows


def _unique_rows_by_id(
    rows: list[dict[str, Any]], label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(rows):
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise CalculationProfileError(
                f"Projection {label}[{index}] has no valid id"
            )
        if item_id in result:
            raise CalculationProfileError(
                f"Projection contains duplicate {label[:-1]} id: {item_id}"
            )
        result[item_id] = item
    return result


def _validate_projection_calendar(calendar: dict[str, Any]) -> None:
    calendar_id = calendar["id"]
    fingerprint = calendar.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise CalculationProfileError(
            f"Projection calendar {calendar_id} has no fingerprint"
        )
    if calendar_id != f"effective-calendar:{fingerprint}":
        raise CalculationProfileError(
            f"Projection calendar {calendar_id} id/fingerprint mismatch"
        )
    week = calendar.get("week")
    if not isinstance(week, list):
        raise CalculationProfileError(
            f"Projection calendar {calendar_id} week must be a list"
        )
    day_types: list[int] = []
    for day_index, day in enumerate(week):
        if not isinstance(day, dict):
            raise CalculationProfileError(
                f"Projection calendar {calendar_id} day {day_index} must be an object"
            )
        day_type = day.get("day_type")
        if type(day_type) is not int or day_type not in range(1, 8):
            raise CalculationProfileError(
                f"Projection calendar {calendar_id} has invalid day_type"
            )
        day_types.append(day_type)
        intervals = day.get("intervals")
        if not isinstance(intervals, list):
            raise CalculationProfileError(
                f"Projection calendar {calendar_id} day {day_type} intervals must be a list"
            )
        previous_finish = -1
        for interval_index, interval in enumerate(intervals):
            if not isinstance(interval, dict):
                raise CalculationProfileError(
                    f"Projection calendar {calendar_id} day {day_type} interval "
                    f"{interval_index} must be an object"
                )
            start = interval.get("start_second")
            finish = interval.get("finish_second")
            if type(start) is not int or type(finish) is not int:
                raise CalculationProfileError(
                    f"Projection calendar {calendar_id} interval seconds must be integers"
                )
            if not (0 <= start < finish <= 86400):
                raise CalculationProfileError(
                    f"Projection calendar {calendar_id} has invalid interval bounds"
                )
            if start < previous_finish:
                raise CalculationProfileError(
                    f"Projection calendar {calendar_id} intervals overlap or are unsorted"
                )
            previous_finish = finish
    if day_types != list(range(1, 8)):
        raise CalculationProfileError(
            f"Projection calendar {calendar_id} week must contain days 1 through 7 once"
        )
    if canonical_sha256(week) != fingerprint:
        raise CalculationProfileError(
            f"Projection calendar {calendar_id} fingerprint mismatch"
        )


def validate_engine_projection(projection: dict[str, Any]) -> None:
    """Fail closed on malformed or tampered engine-neutral input.

    The canonical importer and projection builder normally provide these guarantees,
    but the calculation engine is also a library boundary and must not silently
    collapse duplicate identifiers or accept unsupported numeric precision.
    """

    if not isinstance(projection, dict):
        raise CalculationProfileError("Projection must be an object")
    if projection.get("projection_profile") != PROFILE_VERSION:
        raise CalculationProfileError("Unexpected projection profile")
    if not isinstance(projection.get("source"), dict):
        raise CalculationProfileError("Projection source provenance is missing")

    project = projection.get("project")
    if not isinstance(project, dict):
        raise CalculationProfileError("Projection project is missing")
    if project.get("schedule_from_start") is not True:
        raise CalculationProfileError(
            "Projection must declare schedule-from-start calculation"
        )
    try:
        _parse_datetime(project.get("start"))
    except ValueError as exc:
        raise CalculationProfileError(
            f"Projection project start is invalid: {exc}"
        ) from exc

    calendar_rows = _require_rows(projection.get("calendars"), "calendars")
    activity_rows = _require_rows(projection.get("activities"), "activities")
    relationship_rows = _require_rows(
        projection.get("relationships"), "relationships"
    )

    calendars = _unique_rows_by_id(calendar_rows, "calendars")
    activities = _unique_rows_by_id(activity_rows, "activities")
    _unique_rows_by_id(relationship_rows, "relationships")

    for calendar in calendar_rows:
        _validate_projection_calendar(calendar)

    for activity_id, activity in activities.items():
        source_order = activity.get("source_order")
        if type(source_order) is not int:
            raise CalculationProfileError(
                f"Projection activity {activity_id} source_order must be an integer"
            )
        duration_seconds = activity.get("duration_seconds")
        if not _is_integral_seconds(duration_seconds) or duration_seconds < 0:
            raise CalculationProfileError(
                f"Projection activity {activity_id} duration must be non-negative integral seconds"
            )
        milestone = activity.get("milestone")
        if type(milestone) is not bool:
            raise CalculationProfileError(
                f"Projection activity {activity_id} milestone must be boolean"
            )
        if milestone != (duration_seconds == 0):
            raise CalculationProfileError(
                f"Projection activity {activity_id} milestone/duration mismatch"
            )
        if activity.get("constraint") != "ASAP":
            raise CalculationProfileError(
                f"Projection activity {activity_id} constraint unsupported"
            )
        calendar_ref = activity.get("effective_calendar_ref")
        if calendar_ref not in calendars:
            raise CalculationProfileError(
                f"Projection activity {activity_id} calendar missing"
            )
        if (
            activity.get("profile_calendar_fingerprint")
            != calendars[calendar_ref].get("fingerprint")
        ):
            raise CalculationProfileError(
                f"Projection activity {activity_id} calendar fingerprint mismatch"
            )

    for relationship in relationship_rows:
        relationship_id = relationship["id"]
        source_order = relationship.get("source_order")
        if type(source_order) is not int:
            raise CalculationProfileError(
                f"Projection relationship {relationship_id} source_order must be an integer"
            )
        predecessor = relationship.get("predecessor_ref")
        successor = relationship.get("successor_ref")
        if predecessor not in activities or successor not in activities:
            raise CalculationProfileError("Projection relationship endpoint missing")
        if relationship.get("type") != "FS":
            raise CalculationProfileError("Projection relationship type unsupported")
        lag_seconds = relationship.get("lag_seconds")
        if not _is_integral_seconds(lag_seconds) or lag_seconds > 0:
            raise CalculationProfileError(
                "Projection relationship lag must be non-positive integral seconds"
            )
        if lag_seconds < 0:
            if relationship.get("lag_basis") != "elapsed":
                raise CalculationProfileError(
                    "Negative projection lag must declare elapsed basis"
                )
            if activities[successor].get("milestone"):
                raise CalculationProfileError(
                    "Negative projection lag into a milestone is unsupported"
                )
        elif relationship.get("lag_basis") != "none":
            raise CalculationProfileError(
                "Zero projection lag must declare no lag basis"
            )


def calculate_forward_schedule(projection: dict[str, Any]) -> dict[str, Any]:
    validate_engine_projection(projection)
    project_start = _parse_datetime(projection.get("project", {}).get("start"))
    calendars = {
        item["id"]: tuple(
            (
                day["day_type"],
                tuple(
                    (interval["start_second"], interval["finish_second"])
                    for interval in day["intervals"]
                ),
            )
            for day in item["week"]
        )
        for item in projection["calendars"]
    }
    activities = {item["id"]: item for item in projection["activities"]}
    predecessors: dict[str, list[dict[str, Any]]] = defaultdict(list)
    successors: dict[str, list[str]] = defaultdict(list)
    indegree = {activity_id: 0 for activity_id in activities}
    for relationship in projection["relationships"]:
        predecessor = relationship["predecessor_ref"]
        successor = relationship["successor_ref"]
        predecessors[successor].append(relationship)
        successors[predecessor].append(successor)
        indegree[successor] += 1

    queue = deque(
        sorted(
            (activity_id for activity_id, count in indegree.items() if count == 0),
            key=lambda item: (activities[item]["source_order"], item),
        )
    )
    order: list[str] = []
    calculated: dict[str, tuple[datetime, datetime]] = {}
    while queue:
        activity_id = queue.popleft()
        activity = activities[activity_id]
        order.append(activity_id)
        dependency_candidates = []
        for relationship in predecessors[activity_id]:
            predecessor_finish = calculated[relationship["predecessor_ref"]][1]
            dependency_candidates.append(
                predecessor_finish
                + timedelta(seconds=relationship["lag_seconds"])
            )
        candidate = (
            max(dependency_candidates) if dependency_candidates else project_start
        )
        if activity["milestone"]:
            start = finish = candidate
        else:
            pattern = calendars[activity["effective_calendar_ref"]]
            start = _next_working_time(candidate, pattern)
            finish = _add_working_seconds(
                start, activity["duration_seconds"], pattern
            )
        calculated[activity_id] = (start, finish)
        for successor in sorted(
            successors[activity_id],
            key=lambda item: (activities[item]["source_order"], item),
        ):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)

    if len(order) != len(activities):
        unresolved = sorted(set(activities) - set(order))
        raise CalculationProfileError(
            f"Projection contains a cycle or unresolved dependency: {unresolved[:5]}"
        )

    return {
        "calculation_profile": PROFILE_VERSION,
        "claim_boundary": (
            "Deterministic engine-native forward dates for the eligible subset, including the bounded "
            "negative elapsed-day FS-lead semantic. They are not Microsoft Project early dates or a native compatibility result."
        ),
        "source": projection["source"],
        "activities": [
            {
                "id": activity_id,
                "source_order": activities[activity_id]["source_order"],
                "calculated_start": calculated[activity_id][0].isoformat(),
                "calculated_finish": calculated[activity_id][1].isoformat(),
            }
            for activity_id in order
        ],
        "topological_order_sha256": canonical_sha256(order),
    }


def compare_source_coordinates(
    document: dict[str, Any], calculation: dict[str, Any]
) -> dict[str, Any]:
    if calculation.get("calculation_profile") != PROFILE_VERSION:
        raise CalculationProfileError("Unexpected calculation profile")
    expected_source = _expected_calculation_source(document)
    if calculation.get("source") != expected_source:
        raise CalculationProfileError(
            "Calculation does not match the supplied canonical document"
        )

    calculation_rows = calculation.get("activities")
    if not isinstance(calculation_rows, list):
        raise CalculationProfileError("Calculation activities must be a list")
    calculation_ids: list[str] = []
    for index, item in enumerate(calculation_rows):
        if not isinstance(item, dict):
            raise CalculationProfileError(
                f"Calculation activity {index} must be an object"
            )
        activity_id = item.get("id")
        if not isinstance(activity_id, str) or not activity_id:
            raise CalculationProfileError(
                f"Calculation activity {index} has no valid id"
            )
        calculation_ids.append(activity_id)
    if len(calculation_ids) != len(set(calculation_ids)):
        raise CalculationProfileError("Calculation contains duplicate activity ids")

    # Import locally to keep the projection module's engine import acyclic.
    from .calculation_eligibility import build_calculation_profile

    expected_profile = build_calculation_profile(document)
    expected_ids = list(expected_profile["eligible_activity_ids"])
    calculated_fingerprint = canonical_sha256(sorted(calculation_ids))
    expected_fingerprint = canonical_sha256(sorted(expected_ids))
    if (
        calculated_fingerprint != expected_fingerprint
        or set(calculation_ids) != set(expected_ids)
    ):
        raise CalculationProfileError(
            "Calculation activity cohort does not match the canonical eligibility profile"
        )

    source_by_id = {item["id"]: item for item in document["activities"]}
    differences = []
    exact = 0
    for item in calculation_rows:
        activity_id = item["id"]
        if activity_id not in source_by_id:
            raise CalculationProfileError(
                f"Calculation references activity missing from canonical document: {activity_id}"
            )
        source = source_by_id[activity_id]
        calculated_start = _parse_datetime(item.get("calculated_start"))
        calculated_finish = _parse_datetime(item.get("calculated_finish"))
        source_start = _parse_datetime(source.get("start"))
        source_finish = _parse_datetime(source.get("finish"))
        start_delta = int((calculated_start - source_start).total_seconds())
        finish_delta = int((calculated_finish - source_finish).total_seconds())
        if start_delta == 0 and finish_delta == 0:
            exact += 1
        else:
            differences.append(
                {
                    "activity_id": activity_id,
                    "start_delta_seconds": start_delta,
                    "finish_delta_seconds": finish_delta,
                }
            )
    return {
        "comparison_profile": PROFILE_VERSION,
        "claim_boundary": (
            "Comparison against source Start/Finish observations for the declared subset only. "
            "No Microsoft Project desktop recalculation or round trip was executed."
        ),
        "source": expected_source,
        "counts": {
            "compared_activities": len(calculation_rows),
            "exact_coordinate_matches": exact,
            "coordinate_differences": len(differences),
        },
        "differences": differences,
        "difference_activity_ids_sha256": canonical_sha256(
            sorted(item["activity_id"] for item in differences)
        ),
    }
