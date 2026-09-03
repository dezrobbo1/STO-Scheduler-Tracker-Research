"""P0-G4: two schedules import into two projects and survive a restart with
identical hashes.

Needs a PostgreSQL to talk to and the ``api`` extra installed, so in the bare
suite this file skips -- and, like the BOILER cases, ``STO_REQUIRE_DB=1`` turns
that skip into a failure so a gate is never crossed on evidence that did not
run. The database is created fresh for the run and dropped afterwards.

"Restart" here is a second ``Workspace`` and a second app built over the same
database, with nothing carried over in memory: the document is decoded from
JSONB, re-encoded, re-hashed, and must equal what was stored.
"""

from __future__ import annotations

import os
import secrets
import tempfile
import unittest
import uuid
from pathlib import Path

REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"
ADMIN_URL = os.environ.get("STO_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres")
REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
MIGRATIONS = REPO_ROOT / "infra" / "migrations"
BOILER_BEFORE = Path(os.environ.get("STO_BOILER_BEFORE", "/home/dez/sto-fixtures/boiler-before-no-progress.xml"))
BOILER_DAY5 = Path(os.environ.get("STO_BOILER_DAY5", "/home/dez/BOILER-WG110-day5-candidate.mspdi.xml"))

try:
    import psycopg
    from fastapi.testclient import TestClient
except ImportError as error:  # the bare suite: no extra installed
    if REQUIRE_DB:
        raise RuntimeError(
            f"STO_REQUIRE_DB=1 but the api extra is not installed ({error.name}): "
            "uv sync --extra api"
        ) from error
    psycopg = None  # type: ignore[assignment]
    TestClient = None  # type: ignore[assignment,misc]


def _reachable() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            return True
    except psycopg.OperationalError as error:
        if REQUIRE_DB:
            raise RuntimeError(f"STO_REQUIRE_DB=1 but {ADMIN_URL} is unreachable: {error}") from error
        return False


AVAILABLE = _reachable()


@unittest.skipUnless(
    AVAILABLE,
    "PostgreSQL or the api extra not available; set STO_REQUIRE_DB=1 to make this a failure",
)
class PersistenceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sto.persistence.db import connect

        cls.dbname = f"sto_test_{secrets.token_hex(4)}"
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

    def _client(self):
        """A fresh app over the same database: nothing in memory survives."""

        from sto.api.app import create_app
        from sto.scheduling.working_schedule import Workspace

        workspace = Workspace(connect=self.connect, source_dir=Path(self.tmp.name))
        return TestClient(create_app(workspace))

    def _import(self, client, project_id, path: Path):
        with path.open("rb") as handle:
            response = client.post(
                f"/api/projects/{project_id}/imports",
                files={"file": (path.name, handle, "application/xml")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_two_schedules_survive_a_restart_with_identical_hashes(self):
        with self._client() as client:
            first = client.post("/api/projects", json={"name": "one"}).json()["id"]
            second = client.post("/api/projects", json={"name": "two"}).json()["id"]
            imported = {
                first: self._import(client, first, FIXTURES / "synthetic-basic.mspdi.xml"),
                second: self._import(client, second, FIXTURES / "synthetic-workspace-chain.mspdi.xml"),
            }
        self.assertNotEqual(imported[first]["canonical_hash"], imported[second]["canonical_hash"])

        with self._client() as restarted:
            resident = restarted.app.state.workspace.resident_ids()
            self.assertTrue({uuid.UUID(first), uuid.UUID(second)} <= resident)
            for project_id, before in imported.items():
                after = restarted.get(f"/api/projects/{project_id}/schedule").json()
                self.assertEqual(after["canonical_hash"], before["canonical_hash"])
                self.assertEqual(after["version_id"], before["version_id"])
                self.assertEqual(after["sequence"], 1)

    def test_the_stored_document_rehashes_to_what_was_stored(self):
        """The load path recomputes the hash; here it is checked from outside too."""

        from sto.core.hashing import canonical_sha256
        from sto.core.model import decode_schedule
        from sto.core.model.codec import encode_schedule

        with self._client() as client:
            project = client.post("/api/projects", json={"name": "rehash"}).json()["id"]
            imported = self._import(client, project, FIXTURES / "synthetic-basic.mspdi.xml")
            document = client.get(
                f"/api/projects/{project}/schedule", params={"include": "document"}
            ).json()["document"]
        self.assertEqual(canonical_sha256(document), imported["canonical_hash"])
        self.assertEqual(
            canonical_sha256(encode_schedule(decode_schedule(document))), imported["canonical_hash"]
        )

    def test_reimporting_the_same_file_keeps_every_identifier(self):
        with self._client() as client:
            project = client.post("/api/projects", json={"name": "again"}).json()["id"]
            first = self._import(client, project, FIXTURES / "synthetic-basic.mspdi.xml")
            second = self._import(client, project, FIXTURES / "synthetic-basic.mspdi.xml")
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(second["canonical_hash"], first["canonical_hash"])
        self.assertEqual(second["reconciliation"]["new"], 0)
        self.assertEqual(second["reconciliation"]["missing"], 0)
        self.assertGreater(second["reconciliation"]["matched"], 0)

    def test_a_tampered_version_is_refused_on_load(self):
        with self._client() as client:
            project = client.post("/api/projects", json={"name": "tamper"}).json()["id"]
            self._import(client, project, FIXTURES / "synthetic-basic.mspdi.xml")
        with psycopg.connect(self.url) as conn:
            conn.execute(
                "UPDATE schedule_versions SET canonical_hash = repeat('0', 64) WHERE project_id = %s",
                (uuid.UUID(project),),
            )
            conn.commit()
        with self._client() as restarted:
            response = restarted.get(f"/api/projects/{project}/schedule")
            health = restarted.get("/api/health").json()
        self.assertEqual(response.status_code, 500)
        self.assertIn("hashes to", response.text)
        self.assertEqual(health["status"], "degraded")
        self.assertIn(project, health["integrity_failures"])
        self.assertNotIn(uuid.UUID(project), restarted.app.state.workspace.resident_ids())

    def test_health_reports_the_database(self):
        with self._client() as client:
            body = client.get("/api/health").json()
        self.assertEqual(body["database"], "ok")
        self.assertIn(body["status"], ("ok", "degraded"))  # degraded once the tamper test has run

    def test_an_unknown_project_is_404_everywhere(self):
        with self._client() as client:
            missing = uuid.uuid4()
            self.assertEqual(client.get(f"/api/projects/{missing}").status_code, 404)
            self.assertEqual(client.get(f"/api/projects/{missing}/schedule").status_code, 404)
            self.assertEqual(client.get(f"/api/projects/{missing}/versions").status_code, 404)

    @unittest.skipUnless(
        BOILER_BEFORE.is_file() and BOILER_DAY5.is_file(),
        "real BOILER schedules not present (they stay outside the repository)",
    )
    def test_the_boiler_pair_reconciles_through_persistence_as_it_does_in_memory(self):
        """The recorded counts, now through the database and a restart."""

        with self._client() as client:
            project = client.post("/api/projects", json={"name": "BOILER"}).json()["id"]
            before = self._import(client, project, BOILER_BEFORE)
            day5 = self._import(client, project, BOILER_DAY5)
        self.assertEqual(day5["sequence"], 2)
        self.assertTrue(day5["project_identity_mismatch"], "the two snapshots declare different GUIDs")
        counts = day5["reconciliation"]
        # activities + wbs + assignments + calendars + resources + ...: the
        # per-kind numbers are pinned in test_canonical_model; the totals here
        # must be the same reconciliation, so matched > new and guid_changed
        # covers every matched activity/wbs/assignment.
        self.assertGreater(counts["matched"], counts["new"])
        self.assertGreater(counts["guid_changed"], 0)
        with self._client() as restarted:
            after = restarted.get(f"/api/projects/{project}/schedule").json()
        self.assertEqual(after["canonical_hash"], day5["canonical_hash"])
        self.assertNotEqual(after["canonical_hash"], before["canonical_hash"])


if __name__ == "__main__":
    unittest.main()
