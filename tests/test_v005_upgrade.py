"""A real persisted V004 planner scenario upgraded through V005."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import subprocess
import tempfile
import unittest
import uuid
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


def _url(dbname: str) -> str:
    return ADMIN_URL.rsplit("/", 1)[0] + "/" + dbname


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
class V005UpgradeTests(unittest.TestCase):
    def test_v004_scenario_survives_and_gains_explicit_authorization(self):
        from sto.api.app import create_app
        from sto.api.auth import AuthService, BootstrapClosed
        from sto.persistence import auth_repositories as auth_repo
        from sto.persistence import repositories as repo
        from sto.persistence.db import connect
        from sto.scheduling.working_schedule import Workspace

        dbname = f"sto_v005_upgrade_{secrets.token_hex(4)}"
        source_dir = tempfile.TemporaryDirectory()
        try:
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'CREATE DATABASE "{dbname}"')
            url = _url(dbname)
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
                for path in sorted(MIGRATIONS.glob("V00[1-4]__*.sql")):
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migration_log (filename, sha256) VALUES (%s, %s)",
                        (path.name, hashlib.sha256(path.read_bytes()).hexdigest()),
                    )
                conn.commit()

            connect_v004 = lambda: connect(url)  # noqa: E731 - injected factory
            before = Workspace(connect=connect_v004, source_dir=Path(source_dir.name))
            with connect_v004() as conn:
                project = repo.create_project(conn, name="Persisted V004 planner scenario")
                conn.commit()
            imported = before.import_file(
                project["id"], filename=FIXTURE.name, data=FIXTURE.read_bytes()
            )
            baseline = before.calculate(project["id"])
            initial = before.planner_state(project["id"])
            target = initial["eligible_activities"][0]
            created = before.create_duration_scenario(
                project["id"],
                expected_version_id=initial["current_version_id"],
                activity_uid=target["activity_uid"],
                planned_duration_seconds=target["planned_duration_seconds"] + 3600,
            )
            state_before = before.planner_state(project["id"])
            self.assertEqual(state_before["current_kind"], "scenario")

            # V001/V004 exposed actor columns before a users table existed.
            # A real upgrade must retain any such historical attribution even
            # though only authenticated user IDs are accepted after V005.
            historic_actor = uuid.uuid4()
            with connect_v004() as conn:
                conn.execute(
                    "UPDATE projects SET created_by_user_id=%s WHERE id=%s",
                    (historic_actor, project["id"]),
                )
                conn.execute(
                    "UPDATE source_files SET uploaded_by_user_id=%s WHERE project_id=%s",
                    (historic_actor, project["id"]),
                )
                conn.execute(
                    "UPDATE import_batches SET created_by_user_id=%s WHERE project_id=%s",
                    (historic_actor, project["id"]),
                )
                conn.execute(
                    "UPDATE schedule_versions SET created_by_user_id=%s WHERE project_id=%s",
                    (historic_actor, project["id"]),
                )
                conn.commit()

            applied = subprocess.run(
                [str(ROOT / "scripts" / "db" / "apply-migrations.sh")],
                cwd=ROOT,
                env=_environment(dbname),
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(
                "apply   V005__authentication_and_project_authorization.sql",
                applied.stdout,
            )
            drift = subprocess.run(
                [str(ROOT / "scripts" / "db" / "check-schema-drift.sh")],
                cwd=ROOT,
                env=_environment(dbname),
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("Schema matches infra/migrations (5 migrations, 14 tables)", drift.stdout)

            after = Workspace(connect=connect_v004, source_dir=Path(source_dir.name))
            self.assertEqual(after.rebuild(), 1)
            state_after = after.planner_state(project["id"])
            self.assertEqual(state_after["baseline_version_id"], imported.version_id)
            self.assertEqual(state_after["baseline"]["calculation_id"], baseline.calculation_id)
            self.assertEqual(state_after["current_version_id"], created.scenario_version_id)
            self.assertEqual(
                state_after["scenario"]["calculation_id"], created.calculation_id
            )
            self.assertEqual(
                state_after["scenario"]["fingerprint"],
                state_before["scenario"]["fingerprint"],
            )
            self.assertEqual(state_after["change"], state_before["change"])

            clock = datetime(2035, 4, 5, 12, 0, tzinfo=UTC)
            service = AuthService.for_tests(connect=connect_v004, now=lambda: clock)
            user, secret, _ = service.bootstrap_admin(
                username="upgrade-admin", password="synthetic-upgrade-password"
            )
            with self.assertRaises(BootstrapClosed):
                service.bootstrap_admin(
                    username="second-admin", password="synthetic-upgrade-password"
                )
            client = TestClient(create_app(after, service))
            with client:
                login = client.post(
                    "/api/auth/login",
                    json={
                        "username": "upgrade-admin",
                        "password": "synthetic-upgrade-password",
                        "totp": pyotp.TOTP(secret).at(clock),
                    },
                )
                self.assertEqual(login.status_code, 200, login.text)
                client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
                self.assertEqual(client.get("/api/projects").json(), [])
                self.assertEqual(
                    client.get(f"/api/projects/{project['id']}").status_code, 404
                )
                with connect_v004() as conn:
                    auth_repo.grant_membership(
                        conn,
                        project_id=project["id"],
                        user_id=user["id"],
                        role="admin",
                        created_by_user_id=None,
                    )
                    conn.commit()
                shown = client.get(f"/api/projects/{project['id']}/planner")
                self.assertEqual(shown.status_code, 200, shown.text)
                self.assertEqual(
                    shown.json()["current_version_id"],
                    str(created.scenario_version_id),
                )

            with connect_v004() as conn:
                tables = {
                    row["tablename"]
                    for row in conn.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                    ).fetchall()
                }
                migration_count = conn.execute(
                    "SELECT count(*) AS count FROM schema_migration_log"
                ).fetchone()["count"]
                historic_actors = conn.execute(
                    """
                    SELECT
                      (SELECT count(*) FROM projects WHERE created_by_user_id = %s)
                    + (SELECT count(*) FROM source_files WHERE uploaded_by_user_id = %s)
                    + (SELECT count(*) FROM import_batches WHERE created_by_user_id = %s)
                    + (SELECT count(*) FROM schedule_versions WHERE created_by_user_id = %s)
                      AS count
                    """,
                    (historic_actor,) * 4,
                ).fetchone()["count"]
                with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    conn.execute(
                        "INSERT INTO projects (name, created_by_user_id) VALUES (%s, %s)",
                        ("invalid future actor", uuid.uuid4()),
                    )
                conn.rollback()
            self.assertTrue(
                {
                    "users",
                    "project_memberships",
                    "project_membership_events",
                    "server_sessions",
                    "device_tokens",
                }
                <= tables
            )
            self.assertEqual(migration_count, 5)
            self.assertGreaterEqual(historic_actors, 4)
        finally:
            source_dir.cleanup()
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


if __name__ == "__main__":
    unittest.main()
