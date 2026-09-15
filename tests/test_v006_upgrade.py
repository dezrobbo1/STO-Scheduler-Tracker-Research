"""A real authenticated V005 planner scenario upgraded through V006."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"
ADMIN_URL = os.environ.get(
    "STO_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres"
)
ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "infra" / "migrations"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"

try:
    import psycopg
    import pyotp
    from fastapi.testclient import TestClient
except ImportError as error:
    if REQUIRE_DB:
        raise RuntimeError(
            f"STO_REQUIRE_DB=1 but the api/test extras are missing ({error.name})"
        ) from error
    psycopg = None  # type: ignore[assignment]
    pyotp = None  # type: ignore[assignment]
    TestClient = None  # type: ignore[assignment,misc]


def _reachable() -> bool:
    if psycopg is None or shutil.which("psql") is None:
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


def _environment(dbname: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": "127.0.0.1",
            "PGPORT": "5433",
            "PGUSER": "postgres",
            "PGDATABASE": dbname,
        }
    )
    return environment


@unittest.skipUnless(
    _reachable(),
    "PostgreSQL, psql, or api/test extras unavailable; STO_REQUIRE_DB=1 requires them",
)
class V006UpgradeTests(unittest.TestCase):
    def test_v005_authenticated_scenario_survives_and_can_record_a_reset(self):
        from sto.api.app import create_app
        from sto.api.auth import AuthService
        from sto.persistence import auth_repositories as auth_repo
        from sto.persistence import repositories as repo
        from sto.persistence.db import connect
        from sto.scheduling.working_schedule import Workspace

        dbname = f"sto_v006_upgrade_{secrets.token_hex(4)}"
        source_dir = tempfile.TemporaryDirectory()
        try:
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'CREATE DATABASE "{dbname}"')
            url = ADMIN_URL.rsplit("/", 1)[0] + "/" + dbname
            with psycopg.connect(url) as conn:
                conn.execute(
                    """
                    CREATE TABLE schema_migration_log (
                      filename TEXT PRIMARY KEY,
                      sha256 TEXT NOT NULL,
                      applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      applied_by TEXT NOT NULL DEFAULT current_user,
                      backfilled BOOLEAN NOT NULL DEFAULT false
                    )
                    """
                )
                for path in sorted(MIGRATIONS.glob("V00[1-5]__*.sql")):
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migration_log (filename, sha256) VALUES (%s, %s)",
                        (path.name, hashlib.sha256(path.read_bytes()).hexdigest()),
                    )
                conn.commit()

            connection = lambda: connect(url)  # noqa: E731 - injected factory
            clock = datetime(2035, 5, 6, 12, 0, tzinfo=UTC)
            service = AuthService.for_tests(connect=connection, now=lambda: clock)
            user, secret, _ = service.bootstrap_admin(
                username="v006-admin", password="synthetic-upgrade-password"
            )
            workspace = Workspace(connect=connection, source_dir=Path(source_dir.name))
            with connection() as conn:
                project = repo.create_project(
                    conn, name="Persisted V005 scenario", created_by_user_id=user["id"]
                )
                auth_repo.grant_membership(
                    conn,
                    project_id=project["id"],
                    user_id=user["id"],
                    role="admin",
                    created_by_user_id=user["id"],
                )
                conn.commit()
            imported = workspace.import_file(
                project["id"],
                filename=FIXTURE.name,
                data=FIXTURE.read_bytes(),
                actor_user_id=user["id"],
            )
            baseline = workspace.calculate(project["id"], actor_user_id=user["id"])
            before = workspace.planner_state(project["id"])
            target = before["eligible_activities"][0]
            scenario = workspace.create_duration_scenario(
                project["id"],
                expected_version_id=before["current_version_id"],
                activity_uid=target["activity_uid"],
                planned_duration_seconds=target["planned_duration_seconds"] + 3600,
                actor_user_id=user["id"],
            )
            state_before = workspace.planner_state(project["id"])

            applied = subprocess.run(
                [str(ROOT / "scripts" / "db" / "apply-migrations.sh")],
                cwd=ROOT,
                env=_environment(dbname),
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("apply   V006__scenario_reset_events.sql", applied.stdout)
            drift = subprocess.run(
                [str(ROOT / "scripts" / "db" / "check-schema-drift.sh")],
                cwd=ROOT,
                env=_environment(dbname),
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(
                "Schema matches infra/migrations (6 migrations, 15 tables)",
                drift.stdout,
            )

            rebuilt = Workspace(connect=connection, source_dir=Path(source_dir.name))
            self.assertEqual(rebuilt.rebuild(), 1)
            state_after = rebuilt.planner_state(project["id"])
            self.assertEqual(state_after["baseline_version_id"], imported.version_id)
            self.assertEqual(state_after["baseline"]["calculation_id"], baseline.calculation_id)
            self.assertEqual(state_after["current_version_id"], scenario.scenario_version_id)
            self.assertEqual(
                state_after["scenario"]["fingerprint"],
                state_before["scenario"]["fingerprint"],
            )

            client = TestClient(create_app(rebuilt, service))
            with client:
                login = client.post(
                    "/api/auth/login",
                    json={
                        "username": user["username"],
                        "password": "synthetic-upgrade-password",
                        "totp": pyotp.TOTP(secret).at(clock),
                    },
                )
                self.assertEqual(login.status_code, 200, login.text)
                client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
                reset = client.post(
                    f"/api/projects/{project['id']}/scenario/reset",
                    json={"expected_version_id": str(scenario.scenario_version_id)},
                )
                self.assertEqual(reset.status_code, 200, reset.text)
                self.assertTrue(reset.json()["reset_performed"])

            with connection() as conn:
                event = conn.execute("SELECT * FROM scenario_reset_events").fetchone()
                self.assertEqual(event["actor_user_id"], user["id"])
                self.assertEqual(
                    event["prior_scenario_version_id"], scenario.scenario_version_id
                )
                self.assertEqual(event["restored_baseline_version_id"], imported.version_id)
                self.assertEqual(
                    conn.execute(
                        "SELECT count(*) AS count FROM schedule_versions WHERE project_id=%s",
                        (project["id"],),
                    ).fetchone()["count"],
                    2,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT count(*) AS count FROM schedule_calculations WHERE project_id=%s",
                        (project["id"],),
                    ).fetchone()["count"],
                    2,
                )
                with self.assertRaises(psycopg.errors.CheckViolation):
                    conn.execute("TRUNCATE scenario_reset_events")
                conn.rollback()
        finally:
            source_dir.cleanup()
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


if __name__ == "__main__":
    unittest.main()
