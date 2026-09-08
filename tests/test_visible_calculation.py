"""The calculated schedule, stored and shown beside the imported one (PL13).

`P1-G4` asks that a persisted import shows calculated dates beside the ones it
imported and that a restart reproduces the same result from the same input
hash. Both halves are asked here, through the API, against a real PostgreSQL.

The guards the flow needs are here too, because they are what makes the route
usable by anyone but its author: malformed input is a coded refusal with a
recorded failed batch rather than a server error, an oversized upload is
refused before it is all in memory, and a stored document this code cannot
read fails its own project rather than every project at boot.
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
MIGRATIONS = REPO_ROOT / "infra" / "migrations"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"

try:
    import psycopg
    from fastapi.testclient import TestClient
except ImportError as error:  # the bare suite: no extra installed
    if REQUIRE_DB:
        raise RuntimeError(f"STO_REQUIRE_DB=1 but the api extra is missing ({error.name})") from error
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
class VisibleCalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sto.persistence.db import connect

        cls.dbname = f"sto_visible_{secrets.token_hex(4)}"
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

    def _imported(self, client, name="visible"):
        project = client.post("/api/projects", json={"name": name}).json()["id"]
        with FIXTURE.open("rb") as handle:
            response = client.post(
                f"/api/projects/{project}/imports",
                files={"file": (FIXTURE.name, handle, "application/xml")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        return project

    def test_a_calculation_shows_both_sets_of_dates(self):
        with self._client() as client:
            project = self._imported(client)
            created = client.post(f"/api/projects/{project}/calculations")
            self.assertEqual(created.status_code, 201, created.text)

            shown = client.get(f"/api/projects/{project}/calculations/latest")
            self.assertEqual(shown.status_code, 200, shown.text)
            body = shown.json()

            self.assertEqual(body["fingerprint"], created.json()["fingerprint"])
            self.assertEqual(body["canonical_hash"], created.json()["canonical_hash"])
            self.assertGreater(body["counts"]["activities"], 0)
            self.assertEqual(len(body["activities"]), body["counts"]["activities"])

            for row in body["activities"]:
                with self.subTest(row["activity_uid"]):
                    # The file's dates and the engine's, side by side and never
                    # blended: a row that merged them could not be compared.
                    self.assertIn("source_start", row)
                    self.assertIn("early_start", row)
                    if row["disposition"] == "scheduled":
                        self.assertIsNotNone(row["early_start"])
                        self.assertIsNotNone(row["late_finish"])
                    else:
                        self.assertIsNone(row["early_start"])
                        self.assertIsNotNone(row["exclusion_code"])

    def test_the_answer_says_which_rules_produced_it(self):
        with self._client() as client:
            project = self._imported(client)
            client.post(f"/api/projects/{project}/calculations")
            body = client.get(f"/api/projects/{project}/calculations/latest").json()
            self.assertEqual(body["profiles"]["result"], "sto-result-v1")
            self.assertTrue(body["profiles"]["forward"].startswith("sto-forward-pass-"))
            self.assertLess(body["horizon_start"], body["horizon_finish"])

    def test_the_answer_also_says_what_else_decided_it(self):
        """Dates alone do not explain themselves.

        A status date the plan discarded and an edge it dropped both moved the
        dates on the page, and a reader looking at a row that did not land
        where they expected has no other way to see either.
        """

        with self._client() as client:
            project = self._imported(client)
            client.post(f"/api/projects/{project}/calculations")
            body = client.get(f"/api/projects/{project}/calculations/latest").json()

            self.assertIn("status_time", body)
            self.assertIn("status_time_outside_window", body)
            self.assertFalse(body["status_time_outside_window"])
            self.assertIn("relationships", body)
            for edge in body["relationships"]:
                with self.subTest(edge["relationship_uid"]):
                    self.assertIn(edge["disposition"], {"scheduled", "excluded"})
                    self.assertTrue(edge["code"])

    def test_a_calculation_whose_rows_were_edited_is_not_served(self):
        """The page reads through the fingerprint check, not around it."""

        with self._client() as client:
            project = self._imported(client)
            created = client.post(f"/api/projects/{project}/calculations").json()
            with self.connect() as conn:
                changed = conn.execute(
                    """
                    UPDATE activity_results
                    SET early_finish = early_finish + interval '1 day'
                    WHERE calculation_id = %s AND disposition = 'scheduled'
                    """,
                    (uuid.UUID(created["calculation_id"]),),
                ).rowcount
                conn.commit()
            self.assertGreater(changed, 0)
            refused = client.get(f"/api/projects/{project}/calculations/latest")
            self.assertEqual(refused.status_code, 500, refused.text)
            self.assertIn("fingerprint", refused.json()["detail"])

    def test_a_restart_reproduces_the_same_result_from_the_same_input(self):
        """The half of `P1-G4` that a resident cache could hide."""

        with self._client() as client:
            project = self._imported(client)
            first = client.post(f"/api/projects/{project}/calculations").json()

        # A new app over the same database: no resident schedule, no cache.
        with self._client() as client:
            body = client.get(f"/api/projects/{project}/calculations/latest").json()
            self.assertEqual(body["fingerprint"], first["fingerprint"])
            self.assertEqual(body["canonical_hash"], first["canonical_hash"])

    def test_a_project_with_no_calculation_says_so(self):
        with self._client() as client:
            project = self._imported(client)
            response = client.get(f"/api/projects/{project}/calculations/latest")
            self.assertEqual(response.status_code, 404)

    def test_malformed_input_is_a_coded_refusal_with_a_recorded_batch(self):
        """Not a server error, and not raw bytes on disk nothing refers to."""

        from sto.persistence import repositories as repo

        with self._client() as client:
            project = client.post("/api/projects", json={"name": "malformed"}).json()["id"]
            response = client.post(
                f"/api/projects/{project}/imports",
                files={"file": ("broken.xml", b"<not-a-project/>", "application/xml")},
            )
            self.assertEqual(response.status_code, 422, response.text)
            self.assertNotIn("Traceback", response.text)

        with self.connect() as conn:
            batches = repo.list_import_batches(conn, project_id=project)
        self.assertEqual([row["status"] for row in batches], ["failed"])
        self.assertEqual(batches[0]["error_count"], 1)

    def test_an_oversized_upload_is_refused(self):
        from sto.api.app import MAX_UPLOAD_BYTES

        with self._client() as client:
            project = client.post("/api/projects", json={"name": "large"}).json()["id"]
            oversized = b"x" * (MAX_UPLOAD_BYTES + 1)
            response = client.post(
                f"/api/projects/{project}/imports",
                files={"file": ("big.xml", oversized, "application/xml")},
            )
            self.assertEqual(response.status_code, 413, response.text)

    def test_one_unreadable_project_does_not_take_the_others_with_it(self):
        """The containment F17 asked for, asked of the boot rebuild."""

        from sto.scheduling.working_schedule import Workspace

        with self._client() as client:
            healthy = self._imported(client, name="healthy")
            broken = self._imported(client, name="broken")

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedule_versions
                SET document = document - 'schema_version'
                WHERE project_id = %s
                """,
                (broken,),
            )
            conn.commit()

        workspace = Workspace(connect=self.connect, source_dir=Path(self.tmp.name))
        loaded = workspace.rebuild()
        self.assertGreaterEqual(loaded, 1)
        self.assertIn(__import__("uuid").UUID(broken), workspace.integrity_failures)
        self.assertNotIn(__import__("uuid").UUID(healthy), workspace.integrity_failures)


if __name__ == "__main__":
    unittest.main()
