"""A corpus case as a network the engine can take, shared by the passes' tests.

The corpus is declared in integer coordinates on its own axis -- hours from an
origin -- and the engine takes whatever unit its calendars were compiled in, so
the cases feed it directly with no conversion. That is the point of the engine
taking compiled intervals rather than a schedule.

Every case is hash-checked as it is read, so a drifted case fails rather than
passing against a different oracle; ``tests/test_conformance_corpus.py`` guards
the pins.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from sto import conformance
from sto.core.calendar.arithmetic import CompiledIntervals, intersect_intervals
from sto.core.engine import Network, PlannedActivity, PlannedRelationship
from sto.core.model.enums import ConstraintType, ProgressPolicy, RelationshipType

#: The corpus's progress policies, mapped onto the canonical model's own enum.
PROGRESS_POLICIES = {
    "none": ProgressPolicy.NONE,
    "retained_logic": ProgressPolicy.RETAINED_LOGIC,
    "progress_override": ProgressPolicy.PROGRESS_OVERRIDE,
    "actual_dates": ProgressPolicy.ACTUAL_DATES,
}

#: The corpus names constraints in words; the canonical model names them in the
#: vendors' initials. Anything not here is refused rather than guessed at.
CONSTRAINT_TYPES = {
    "start_no_earlier_than": ConstraintType.SNET,
    "finish_no_earlier_than": ConstraintType.FNET,
    "must_start_on": ConstraintType.MSO,
    "must_finish_on": ConstraintType.MFO,
    "start_no_later_than": ConstraintType.SNLT,
    "finish_no_later_than": ConstraintType.FNLT,
    "as_late_as_possible": ConstraintType.ALAP,
}


def _uid(case_id: str, local_id: str) -> UUID:
    """A stable identifier for a corpus row, so a failure names the same uid twice."""

    return uuid5(NAMESPACE_URL, f"sto-conformance/{case_id}/{local_id}")


def _load(case_id: str) -> dict:
    return conformance.load_case(case_id)


def _build_network(case_id: str, case: dict) -> tuple[Network, dict[str, UUID]]:
    """A corpus case as a network, refusing anything the mapping does not cover."""

    schedule = case["schedule"]
    calendars = {
        c["id"]: tuple(tuple(i) for i in c["working_intervals"])
        for c in schedule["calendars"]
    }
    resources = {r["id"]: r for r in schedule.get("resources", [])}

    uid_by_id: dict[str, UUID] = {}
    activities: list[PlannedActivity] = []
    for activity in schedule["activities"]:
        uid = _uid(case_id, activity["id"])
        uid_by_id[activity["id"]] = uid

        intervals = calendars[activity["calendar_id"]]
        for assignment in activity.get("assignments", []):
            resource = resources[assignment["resource_id"]]
            if resource.get("calendar_id"):
                intervals = intersect_intervals(intervals, calendars[resource["calendar_id"]])

        declared = activity.get("constraints", [])
        if len(declared) > 1:
            raise ValueError(f"{case_id}: more than one constraint is not mapped")
        constraint_type = ConstraintType.ASAP
        coordinate = None
        for constraint in declared:
            mapped = CONSTRAINT_TYPES.get(constraint["type"])
            if mapped is None:
                raise ValueError(f"{case_id}: unmapped constraint {constraint['type']}")
            constraint_type, coordinate = mapped, constraint["value"]

        activities.append(
            PlannedActivity(
                uid=uid,
                duration=activity["duration"],
                calendar=CompiledIntervals.of(intervals),
                constraint_type=constraint_type,
                constraint_coordinate=coordinate,
                actual_start=activity.get("actual_start"),
                actual_finish=activity.get("actual_finish"),
                remaining_duration=activity.get("remaining_duration"),
            )
        )

    relationships = tuple(
        PlannedRelationship(
            uid=_uid(case_id, row["id"]),
            predecessor_uid=uid_by_id[row["predecessor_id"]],
            successor_uid=uid_by_id[row["successor_id"]],
            type=RelationshipType(row["type"]),
            lag=row["lag"],
            lag_calendar=(
                CompiledIntervals.of(calendars[row["lag_calendar"]])
                if row.get("lag_calendar")
                else None
            ),
        )
        for row in schedule["relationships"]
    )

    network = Network(
        activities=tuple(activities),
        relationships=relationships,
        project_start=schedule["project"]["project_start"],
        horizon=schedule["time_axis"]["horizon"],
        status_time=schedule["project"].get("status_time"),
    )
    return network, uid_by_id


def _progress_policy(case: dict) -> ProgressPolicy:
    """The case's declared progress policy, refused rather than guessed at.

    The corpus spells its policies exactly as the canonical model does, so this
    is an identity mapping written out rather than assumed: a policy the mapping
    does not cover raises instead of quietly becoming the default.
    """

    declared = case["schedule"]["project"].get("progress_policy")
    if declared is None:
        return ProgressPolicy.RETAINED_LOGIC
    policy = PROGRESS_POLICIES.get(declared)
    if policy is None:
        raise ValueError(f"{case['case_id']}: unmapped progress policy {declared}")
    return policy
