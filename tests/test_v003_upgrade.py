"""A real V002 installation upgraded through V003, with data already present.

Fresh-schema migration CI cannot answer this: V003 protects a table and rows
that V002 introduced. This test creates the immediately preceding state,
stores a representative import and calculation through the application, then
uses the supported migration script and reconstructs the workspace.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"
ADMIN_URL = os.environ.get(
    "STO_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres"
)
ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "infra" / "migrations"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"

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


AVAILABLE = _reachable()


@unittest.skipUnless(
    AVAILABLE,
    "PostgreSQL or the api extra not available; set STO_REQUIRE_DB=1 to require it",
)
class V003UpgradeTests(unittest.TestCase):
    def test_v002_data_survives_the_supported_v003_upgrade(self):
        from sto.persistence import repositories as repo
        from sto.persistence.db import connect
        from sto.scheduling.working_schedule import Workspace

        dbname = f"sto_v003_upgrade_{secrets.token_hex(4)}"
        temporary = tempfile.TemporaryDirectory()
        try:
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'CREATE DATABASE "{dbname}"')
            url = ADMIN_URL.rsplit("/", 1)[0] + "/" + dbname

            # This is an existing, fully recorded V002 installation, not a
            # fresh database over which all three files are applied together.
            with psycopg.connect(url) as conn:
                for name in (
                    "V001__projects_sources_and_schedule_versions.sql",
                    "V002__calculated_results.sql",
                ):
                    path = MIGRATIONS / name
                    conn.execute(path.read_text(encoding="utf-8"))
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
                for name in (
                    "V001__projects_sources_and_schedule_versions.sql",
                    "V002__calculated_results.sql",
                ):
                    path = MIGRATIONS / name
                    conn.execute(
                        "INSERT INTO schema_migration_log (filename, sha256) VALUES (%s, %s)",
                        (name, hashlib.sha256(path.read_bytes()).hexdigest()),
                    )
                conn.commit()

            connect_v002 = lambda: connect(url)  # noqa: E731 - injected connection factory
            before = Workspace(connect=connect_v002, source_dir=Path(temporary.name))
            with connect_v002() as conn:
                project = repo.create_project(conn, name="V003 upgrade fixture")
                conn.commit()
            imported = before.import_file(
                project["id"], filename=FIXTURE.name, data=FIXTURE.read_bytes()
            )
            calculated = before.calculate(project["id"])
            readable_before = before.read_calculation(
                project["id"], calculation_id=calculated.calculation_id
            )
            self.assertEqual(readable_before.version_id, imported.version_id)
            self.assertEqual(readable_before.result.fingerprint, calculated.fingerprint)

            parsed = urlparse(url)
            environment = os.environ.copy()
            environment.update(
                {
                    "PGHOST": parsed.hostname or "127.0.0.1",
                    "PGPORT": str(parsed.port or 5432),
                    "PGUSER": parsed.username or "postgres",
                    "PGDATABASE": dbname,
                }
            )
            if parsed.password:
                environment["PGPASSWORD"] = parsed.password
            applied = subprocess.run(
                [str(ROOT / "scripts" / "db" / "apply-migrations.sh")],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("apply   V003__calculation_version_is_immutable.sql", applied.stdout)
            # The supported command always advances to the repository's
            # current schema. PL14 adds V004 after the V003 proof was first
            # recorded, so an installation at V002 receives both in order.
            self.assertIn("apply   V004__planner_scenario_changes.sql", applied.stdout)
            drift = subprocess.run(
                [str(ROOT / "scripts" / "db" / "check-schema-drift.sh")],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("Schema matches infra/migrations", drift.stdout)

            # Reconstruct the application from PostgreSQL. The pre-upgrade
            # version, head and stored result all retain their identity.
            after = Workspace(connect=connect_v002, source_dir=Path(temporary.name))
            self.assertEqual(after.rebuild(), 1)
            head = after.load(project["id"])
            reread = after.read_calculation(
                project["id"], calculation_id=calculated.calculation_id
            )
            self.assertEqual(head.version_id, imported.version_id)
            self.assertEqual(head.canonical_hash, imported.canonical_hash)
            self.assertEqual(reread.version_id, calculated.version_id)
            self.assertEqual(reread.result.fingerprint, calculated.fingerprint)

            # The upgraded schema accepts and serves a new calculation, while
            # V003 refuses the lineage corruption it was added to prevent.
            new_run = after.calculate(project["id"], before=timedelta(days=30))
            self.assertNotEqual(new_run.calculation_id, calculated.calculation_id)
            self.assertEqual(
                after.read_calculation(
                    project["id"], calculation_id=new_run.calculation_id
                ).result.fingerprint,
                new_run.fingerprint,
            )
            second = after.import_file(
                project["id"], filename="again.xml", data=FIXTURE.read_bytes()
            )
            with self.assertRaises(psycopg.errors.CheckViolation):
                with connect_v002() as conn:
                    conn.execute(
                        "UPDATE schedule_calculations SET version_id = %s WHERE id = %s",
                        (second.version_id, calculated.calculation_id),
                    )
                    conn.commit()
        finally:
            temporary.cleanup()
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


if __name__ == "__main__":
    unittest.main()
