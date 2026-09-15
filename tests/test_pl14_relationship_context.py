"""Regression coverage for PL14's relationship-level assumption boundary."""

from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"

try:
    import psycopg  # noqa: F401
except ImportError as error:
    if REQUIRE_DB:
        raise RuntimeError(
            f"STO_REQUIRE_DB=1 but the persistence extra is missing ({error.name})"
        ) from error
    raise unittest.SkipTest(
        "persistence extra unavailable; STO_REQUIRE_DB=1 makes this a failure"
    ) from error

from sto.core.engine.result import (
    SCHEDULED,
    ActivityResult,
    Provenance,
    RelationshipResult,
    ScheduleResult,
)
from sto.core.model.entities import Activity, Duration, Relationship, Schedule
from sto.scheduling.working_schedule import (
    ScenarioRejected,
    StoredCalculation,
    WorkingSchedule,
    Workspace,
    _with_relationship_context,
)


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class RelationshipContextTests(unittest.TestCase):
    def setUp(self):
        self.predecessor = uuid.uuid4()
        self.successor = uuid.uuid4()
        self.unrelated = uuid.uuid4()
        self.relationship = uuid.uuid4()
        self.schedule = Schedule(
            schedule_id="pl14-relationship-context",
            activities=(
                Activity(
                    uid=self.predecessor,
                    name="Predecessor",
                    planned_duration=Duration(3600),
                    remaining_duration=Duration(3600),
                ),
                Activity(
                    uid=self.successor,
                    name="Successor",
                    planned_duration=Duration(3600),
                    remaining_duration=Duration(3600),
                ),
                Activity(
                    uid=self.unrelated,
                    name="Unrelated",
                    planned_duration=Duration(3600),
                    remaining_duration=Duration(3600),
                ),
            ),
            relationships=(
                Relationship(
                    uid=self.relationship,
                    predecessor_uid=self.predecessor,
                    successor_uid=self.successor,
                    lag=Duration(3600),
                ),
            ),
        )

    def projected(self):
        return {
            "relationships": [
                {
                    "relationship_uid": self.relationship,
                    "disposition": SCHEDULED,
                    "code": "RELATIONSHIP_LAG_ON_PROJECT_CALENDAR",
                    "detail": "unmeasured lag calendar",
                }
            ],
            "activities": [
                {
                    "activity_uid": self.predecessor,
                    "assumptions": [],
                    "disposition": SCHEDULED,
                },
                {
                    "activity_uid": self.successor,
                    "assumptions": [],
                    "disposition": SCHEDULED,
                },
                {
                    "activity_uid": self.unrelated,
                    "assumptions": [],
                    "disposition": SCHEDULED,
                },
            ],
        }

    def test_exceptional_relationship_context_is_visible_on_both_endpoints(self):
        decorated = _with_relationship_context(self.schedule, self.projected())
        self.assertIsNotNone(decorated)
        by_uid = {row["activity_uid"]: row for row in decorated["activities"]}
        code = "RELATIONSHIP_LAG_ON_PROJECT_CALENDAR"
        self.assertEqual(by_uid[self.predecessor]["assumptions"], [code])
        self.assertEqual(by_uid[self.successor]["assumptions"], [code])
        self.assertEqual(by_uid[self.unrelated]["assumptions"], [])

    def test_direct_scenario_request_rejects_relationship_assumption(self):
        project_id = uuid.uuid4()
        version_id = uuid.uuid4()
        calculation_id = uuid.uuid4()
        now = datetime(2026, 1, 5, 8)
        provenance = Provenance(
            canonical_hash="baseline-hash",
            epoch=now,
            horizon_start=now,
            horizon_finish=datetime(2026, 1, 12, 8),
            progress_policy="retained_logic",
            critical_float_threshold=0,
        )
        result = ScheduleResult(
            provenance=provenance,
            activities=(
                ActivityResult(uid=self.successor, disposition=SCHEDULED),
            ),
            summaries=(),
            relationships=(
                RelationshipResult(
                    uid=self.relationship,
                    disposition=SCHEDULED,
                    code="RELATIONSHIP_LAG_ON_PROJECT_CALENDAR",
                    detail="unmeasured lag calendar",
                ),
            ),
        )
        working = WorkingSchedule(
            project_id=project_id,
            version_id=version_id,
            sequence=1,
            canonical_hash="baseline-hash",
            schedule=self.schedule,
            identity=None,  # not reached: the request must fail before derivation
        )
        stored = StoredCalculation(
            project_id=project_id,
            version_id=version_id,
            calculation_id=calculation_id,
            computed_at=now,
            result=result,
            schedule=self.schedule,
        )
        workspace = Workspace(connect=lambda: _Connection())

        with (
            patch.object(workspace, "load", return_value=working),
            patch.object(workspace, "read_calculation", return_value=stored),
            patch(
                "sto.scheduling.working_schedule.repo.head_version",
                return_value=None,
            ),
        ):
            with self.assertRaises(ScenarioRejected) as raised:
                workspace.create_duration_scenario(
                    project_id,
                    expected_version_id=version_id,
                    activity_uid=self.successor,
                    planned_duration_seconds=7200,
                )

        self.assertEqual(raised.exception.code, "ACTIVITY_HAS_ASSUMPTIONS")
        self.assertIn("RELATIONSHIP_LAG_ON_PROJECT_CALENDAR", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
