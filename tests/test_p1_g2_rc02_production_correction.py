"""Production regressions for the bounded P1-G2 RC02 inactive-boundary rule."""
from __future__ import annotations

from datetime import datetime
import unittest
from uuid import NAMESPACE_URL, UUID, uuid5

from calculation_fixture import _activity, _document, _relationship

from sto.core.calendar.arithmetic import CompiledIntervals
from sto.core.engine import (
    BackwardPassError,
    Network,
    PlannedActivity,
    PlannedRelationship,
    backward_pass,
    build_plan,
    float_analysis,
    forward_pass,
    validate_result,
)
from sto.core.model.enums import RelationshipType
from sto.core.model.migrate.sto_v011 import migrate

CONTINUOUS = CompiledIntervals.of(((0, 100),))
HORIZON = (datetime(2026, 1, 1), datetime(2026, 2, 1))


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sto-rc02-production/{name}")


def activity(name: str, duration: int) -> PlannedActivity:
    return PlannedActivity(uid(name), duration, CONTINUOUS)


def edge(name: str, pred: str, succ: str, *, boundary: str | None = None) -> PlannedRelationship:
    return PlannedRelationship(
        uid(name),
        uid(pred),
        uid(succ),
        RelationshipType.FS,
        0,
        None,
        None if boundary is None else uid(boundary),
    )


def fanout(*, s1_duration: int, s2_duration: int) -> Network:
    boundary = "inactive-middle"
    return Network(
        activities=(
            activity("P", 2),
            activity("S1", s1_duration),
            activity("S2", s2_duration),
        ),
        relationships=(
            edge("B1", "P", "S1", boundary=boundary),
            edge("B2", "P", "S2", boundary=boundary),
        ),
        project_start=0,
        horizon=100,
    )


class NativeInactiveBoundaryEngineTests(unittest.TestCase):
    def test_all_boundary_successors_bind_forward_but_latest_binds_backward(self):
        network = fanout(s1_duration=5, s2_duration=2)
        forward = forward_pass(network)
        self.assertEqual(forward.by_uid()[uid("S1")].early_start, 2)
        self.assertEqual(forward.by_uid()[uid("S2")].early_start, 2)

        backward = backward_pass(network, forward)
        late = backward.by_uid()
        self.assertEqual(late[uid("S1")].late_start, 2)
        self.assertEqual(late[uid("S2")].late_start, 5)
        self.assertEqual(late[uid("P")].late_finish, 5)
        self.assertEqual(late[uid("P")].driving_relationship_uid, uid("B2"))

    def test_reversing_successor_lengths_reverses_the_backward_winner(self):
        network = fanout(s1_duration=2, s2_duration=5)
        forward = forward_pass(network)
        backward = backward_pass(network, forward)
        late = backward.by_uid()
        self.assertEqual(late[uid("S1")].late_start, 5)
        self.assertEqual(late[uid("S2")].late_start, 2)
        self.assertEqual(late[uid("P")].late_finish, 5)
        self.assertEqual(late[uid("P")].driving_relationship_uid, uid("B1"))

    def test_equal_successor_late_boundaries_fail_closed(self):
        network = fanout(s1_duration=2, s2_duration=2)
        forward = forward_pass(network)
        with self.assertRaisesRegex(BackwardPassError, "SCHEDULE_INACTIVE_BOUNDARY_LATE_TIE"):
            backward_pass(network, forward)

    def test_free_float_retains_the_inactive_edge_reporting_boundary(self):
        boundary = "inactive-middle"
        network = Network(
            activities=(
                activity("P", 2),
                activity("O1", 10),
                activity("O2", 12),
                activity("S1", 1),
                activity("S2", 2),
            ),
            relationships=(
                edge("B1", "P", "S1", boundary=boundary),
                edge("B2", "P", "S2", boundary=boundary),
                edge("R1", "O1", "S1"),
                edge("R2", "O2", "S2"),
            ),
            project_start=0,
            horizon=100,
        )
        forward = forward_pass(network)
        self.assertEqual(forward.by_uid()[uid("S1")].early_start, 10)
        self.assertEqual(forward.by_uid()[uid("S2")].early_start, 12)
        backward = backward_pass(network, forward)
        floats = float_analysis(network, forward, backward)
        self.assertEqual(floats.by_uid()[uid("P")].free_float, 0)
        self.assertEqual(validate_result(network, forward, backward, floats), ())

    def test_boundary_metadata_changes_the_network_identity(self):
        special = fanout(s1_duration=5, s2_duration=2)
        ordinary = Network(
            activities=special.activities,
            relationships=tuple(
                PlannedRelationship(
                    row.uid,
                    row.predecessor_uid,
                    row.successor_uid,
                    row.type,
                    row.lag,
                    row.lag_calendar,
                )
                for row in special.relationships
            ),
            project_start=special.project_start,
            horizon=special.horizon,
        )
        self.assertNotEqual(special.fingerprint(), ordinary.fingerprint())


class NativeInactiveBoundaryPlanTests(unittest.TestCase):
    @staticmethod
    def _plan(*, second_successor: bool = True, inactive_predecessor: bool = False):
        activities = [
            _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T10:00:00", duration_seconds=7200, active=not inactive_predecessor),
            _activity(2, start="2026-01-05T10:00:00", finish="2026-01-05T12:00:00", duration_seconds=7200, active=False),
            _activity(3, start="2026-01-05T10:00:00", finish="2026-01-05T11:00:00", duration_seconds=3600),
        ]
        relationships = [_relationship(1, 1, 2), _relationship(2, 2, 3)]
        if second_successor:
            activities.append(
                _activity(4, start="2026-01-05T10:00:00", finish="2026-01-05T10:30:00", duration_seconds=1800)
            )
            relationships.append(_relationship(3, 2, 4))
        schedule, _, _ = migrate(_document(activities, relationships=relationships))
        return schedule, build_plan(schedule, HORIZON)

    def test_measured_shape_builds_native_boundary_edges_not_assumptions(self):
        schedule, plan = self._plan()
        inactive_uid = schedule.activities[1].uid
        boundary = [row for row in plan.network.relationships if row.inactive_boundary_uid]
        self.assertEqual(len(boundary), 2)
        self.assertEqual({row.inactive_boundary_uid for row in boundary}, {inactive_uid})
        self.assertEqual(
            {row.successor_uid for row in boundary},
            {schedule.activities[2].uid, schedule.activities[3].uid},
        )
        self.assertNotIn("ACTIVITY_SUCCESSOR_OF_INACTIVE", plan.assumed_by_code())


    def test_parallel_direct_predecessor_successor_edge_stays_labelled(self):
        activities = [
            _activity(1, start="2026-01-05T08:00:00", finish="2026-01-05T10:00:00", duration_seconds=7200),
            _activity(2, start="2026-01-05T10:00:00", finish="2026-01-05T12:00:00", duration_seconds=7200, active=False),
            _activity(3, start="2026-01-05T10:00:00", finish="2026-01-05T11:00:00", duration_seconds=3600),
        ]
        relationships = [
            _relationship(1, 1, 2),
            _relationship(2, 2, 3),
            _relationship(3, 1, 3),
        ]
        schedule, _, _ = migrate(_document(activities, relationships=relationships))
        plan = build_plan(schedule, HORIZON)
        self.assertEqual(
            [row for row in plan.network.relationships if row.inactive_boundary_uid],
            [],
        )
        self.assertEqual(
            plan.assumed_by_code().get("ACTIVITY_SUCCESSOR_OF_INACTIVE"),
            1,
        )

    def test_inactive_chain_without_active_predecessor_stays_labelled(self):
        _, plan = self._plan(second_successor=False, inactive_predecessor=True)
        self.assertEqual(
            plan.assumed_by_code().get("ACTIVITY_SUCCESSOR_OF_INACTIVE"),
            1,
        )
        self.assertEqual(
            [row for row in plan.network.relationships if row.inactive_boundary_uid],
            [],
        )


if __name__ == "__main__":
    unittest.main()
