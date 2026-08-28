from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any

from .calculation_calendar import _add_working_seconds, _next_working_time
from .calculation_common import CalculationProfileError, PROFILE_VERSION, _parse_datetime
from .provenance import canonical_sha256


def _expected_calculation_source(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": document["schema_version"],
        "importer_profile": document["importer_profile"],
        "source_sha256": document["source"]["sha256"],
        "document_key": document["source"]["document_key"],
        "canonical_sha256": canonical_sha256(document),
    }


def calculate_forward_schedule(projection: dict[str, Any]) -> dict[str, Any]:
    if projection.get("projection_profile") != PROFILE_VERSION:
        raise CalculationProfileError("Unexpected projection profile")
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
        if predecessor not in activities or successor not in activities:
            raise CalculationProfileError("Projection relationship endpoint missing")
        if relationship.get("type") != "FS":
            raise CalculationProfileError("Projection relationship type unsupported")
        lag_seconds = relationship.get("lag_seconds")
        if not isinstance(lag_seconds, (int, float)) or lag_seconds > 0:
            raise CalculationProfileError("Projection relationship lag unsupported")
        if lag_seconds < 0 and relationship.get("lag_basis") != "elapsed":
            raise CalculationProfileError("Negative projection lag must declare elapsed basis")
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
                predecessor_finish + timedelta(seconds=relationship["lag_seconds"])
            )
        candidate = max([project_start] + dependency_candidates)
        if activity["milestone"]:
            start = finish = candidate
        else:
            pattern = calendars[activity["effective_calendar_ref"]]
            start = _next_working_time(candidate, pattern)
            finish = _add_working_seconds(start, activity["duration_seconds"], pattern)
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

    source_by_id = {item["id"]: item for item in document["activities"]}
    differences = []
    exact = 0
    for item in calculation["activities"]:
        activity_id = item.get("id")
        if activity_id not in source_by_id:
            raise CalculationProfileError(
                f"Calculation references activity missing from canonical document: {activity_id}"
            )
        source = source_by_id[activity_id]
        calculated_start = _parse_datetime(item["calculated_start"])
        calculated_finish = _parse_datetime(item["calculated_finish"])
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
            "compared_activities": len(calculation["activities"]),
            "exact_coordinate_matches": exact,
            "coordinate_differences": len(differences),
        },
        "differences": differences,
        "difference_activity_ids_sha256": canonical_sha256(
            sorted(item["activity_id"] for item in differences)
        ),
    }
