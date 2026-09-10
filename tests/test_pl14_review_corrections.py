"""Regressions for the final PL14 review findings.

These tests keep a planner scenario tied to the exact baseline calculation it is
presented against. They require PostgreSQL because the defect is a durable-state
race/context error rather than a pure engine calculation.
"""

from __future__ import annotations

import os
import secrets
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"
ADMIN_URL = os.environ.get(
    "STO_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres"
)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"
MIGRATIONS = ROOT / "infra" / "migrations"

try:
    import psycopg
except ImportError as error:
    if REQUIRE_DB:
        raise RuntimeError(
            f"STO_REQUIRE_DB=1 but psycopg is not installed ({error.name})"
        ) from error
    psycopg = None  # type: ignore[assignment]


def _reachable() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            return True
    except psycopg.OperationalError as error:
        if REQUIRE_DB:
            raise RuntimeError(
                f"STO_REQUIRE_DB=1 but {ADMIN_URL} is unreachable: {error}"
            ) from error
        return False


@unittest.skipUnless(
    _reachable(),
    "PostgreSQL unavailable; STO_REQUIRE_DB=1 makes this a failure",
)
class ScenarioCalculationContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sto.persistence.db import connect

        cls.dbname = f"sto_pl14_review_{secrets.token_hex(4)}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{cls.dbname}"')
        cls.url = ADMIN_URL.rsplit("/", 1)[0] + "/" + cls.dbname
        with psycopg.connect(cls.url) as conn:
            for path in sorted(MIGRATIONS.glob("V*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))
            conn.commit()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.connect = staticmethod(lambda url=cls.url: connect(url))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{cls.dbname}" WITH (FORCE)')

    def prepared(self, name: str):
        from sto.persistence import repositories as repo
        from sto.scheduling.working_schedule import Workspace

        workspace = Workspace(connect=self.connect, source_dir=Path(self.tmp.name))
        with self.connect() as conn:
            project = repo.create_project(conn, name=name)
            conn.commit()
        project_id = project["id"]
        workspace.import_file(
            project_id, filename=FIXTURE.name, data=FIXTURE.read_bytes()
        )
        workspace.calculate(
            project_id,
            before=timedelta(days=30),
            after=timedelta(days=120),
        )
        state = workspace.planner_state(project_id)
        target = state["eligible_activities"][0]
        return workspace, project_id, state, target

    def test_scenario_reuses_the_active_baseline_calculation_context(self):
        workspace, project_id, initial, target = self.prepared("context")

        workspace.create_duration_scenario(
            project_id,
            expected_version_id=initial["current_version_id"],
            activity_uid=target["activity_uid"],
            planned_duration_seconds=target["planned_duration_seconds"] + 3600,
        )
        state = workspace.planner_state(project_id)
        self.assertIsNotNone(state["scenario"])
        for field in (
            "epoch",
            "horizon_start",
            "horizon_finish",
            "progress_policy",
            "critical_float_threshold",
            "status_time",
            "status_time_outside_window",
            "resource_calendars_apply",
            "profiles",
        ):
            with self.subTest(field):
                self.assertEqual(state["scenario"][field], state["baseline"][field])

    def test_scenario_is_not_published_after_the_baseline_calculation_moves(self):
        from sto.persistence import repositories as repo
        from sto.scheduling.working_schedule import StaleSchedule, Workspace

        workspace, project_id, initial, target = self.prepared("calculation-race")
        baseline_working = workspace.load(project_id, refresh=True)
        self.assertIsNotNone(baseline_working)
        original_calculate = Workspace._calculate_working
        advanced = False

        def calculate_then_advance(working, *, before, after):
            nonlocal advanced
            result = original_calculate(working, before=before, after=after)
            if not advanced:
                advanced = True
                replacement = original_calculate(
                    baseline_working,
                    before=timedelta(days=20),
                    after=timedelta(days=120),
                )
                with workspace.connect() as conn:
                    inserted = repo.insert_calculation(
                        conn,
                        project_id=project_id,
                        version_id=baseline_working.version_id,
                        result=replacement,
                    )
                    conn.commit()
                self.assertIsNotNone(inserted)
            return result

        with patch.object(
            workspace, "_calculate_working", side_effect=calculate_then_advance
        ):
            with self.assertRaises(StaleSchedule):
                workspace.create_duration_scenario(
                    project_id,
                    expected_version_id=initial["current_version_id"],
                    activity_uid=target["activity_uid"],
                    planned_duration_seconds=target["planned_duration_seconds"] + 3600,
                )

        with workspace.connect() as conn:
            scenario_head = repo.head_version(
                conn,
                project_id=project_id,
                kind="scenario",
                with_document=False,
            )
            scenario_versions = conn.execute(
                "SELECT count(*) FROM schedule_versions "
                "WHERE project_id=%s AND kind='scenario'",
                (project_id,),
            ).fetchone()[0]
        self.assertIsNone(scenario_head)
        self.assertEqual(scenario_versions, 0)


if __name__ == "__main__":
    unittest.main()
