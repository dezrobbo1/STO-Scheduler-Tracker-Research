"""PL14's persisted duration scenario, through the real API and PostgreSQL."""

from __future__ import annotations

import os
import secrets
import tempfile
import unittest
import uuid
from pathlib import Path

REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"
ADMIN_URL = os.environ.get(
    "STO_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres"
)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"
MIGRATIONS = ROOT / "infra" / "migrations"

try:
    import psycopg
    from fastapi.testclient import TestClient
except ImportError as error:
    if REQUIRE_DB:
        raise RuntimeError(
            f"STO_REQUIRE_DB=1 but the api extra is missing ({error.name})"
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
            raise RuntimeError(
                f"STO_REQUIRE_DB=1 but {ADMIN_URL} is unreachable: {error}"
            ) from error
        return False


@unittest.skipUnless(
    _reachable(),
    "PostgreSQL or api extra unavailable; STO_REQUIRE_DB=1 makes this a failure",
)
class PlannerScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sto.persistence.db import connect

        cls.dbname = f"sto_pl14_{secrets.token_hex(4)}"
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

    def client(self):
        from sto.api.app import create_app
        from sto.scheduling.working_schedule import Workspace

        workspace = Workspace(connect=self.connect, source_dir=Path(self.tmp.name))
        return TestClient(create_app(workspace))

    def prepared(self, name="planner"):
        client = self.client()
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        project = client.post("/api/projects", json={"name": name}).json()["id"]
        with FIXTURE.open("rb") as handle:
            imported = client.post(
                f"/api/projects/{project}/imports",
                files={"file": (FIXTURE.name, handle, "application/xml")},
            )
        self.assertEqual(imported.status_code, 201, imported.text)
        calculated = client.post(f"/api/projects/{project}/calculations")
        self.assertEqual(calculated.status_code, 201, calculated.text)
        return client, project, imported.json(), calculated.json()

    @staticmethod
    def activity(state, name, side="baseline"):
        return next(row for row in state[side]["activities"] if row["name"] == name)

    def test_duration_edit_moves_downstream_and_survives_restart(self):
        client, project, imported, baseline_summary = self.prepared()
        initial = client.get(f"/api/projects/{project}/planner").json()
        target = next(
            row for row in initial["eligible_activities"]
            if row["name"] == "Isolate equipment"
        )
        self.assertEqual(target["planned_duration_seconds"], 4 * 3600)

        response = client.post(
            f"/api/projects/{project}/scenario",
            json={
                "expected_version_id": initial["current_version_id"],
                "activity_uid": target["activity_uid"],
                "planned_duration_seconds": 8 * 3600,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        state = response.json()
        self.assertEqual(state["current_kind"], "scenario")
        self.assertEqual(state["baseline_version_id"], imported["version_id"])
        self.assertNotEqual(state["current_version_id"], imported["version_id"])
        self.assertEqual(state["change"]["before_seconds"], 4 * 3600)
        self.assertEqual(state["change"]["after_seconds"], 8 * 3600)
        self.assertEqual(state["change"]["remaining_before_seconds"], 4 * 3600)
        self.assertEqual(state["change"]["remaining_after_seconds"], 8 * 3600)

        baseline_target = self.activity(state, "Isolate equipment")
        scenario_target = self.activity(state, "Isolate equipment", "scenario")
        baseline_downstream = self.activity(state, "Execute inspection")
        scenario_downstream = self.activity(state, "Execute inspection", "scenario")
        self.assertGreaterEqual(
            scenario_downstream["early_start"], scenario_target["early_finish"]
        )
        self.assertNotEqual(
            baseline_target["early_finish"], scenario_target["early_finish"]
        )
        self.assertNotEqual(
            baseline_downstream["early_start"], scenario_downstream["early_start"]
        )
        self.assertEqual(
            {r["activity_uid"] for r in state["baseline"]["activities"]},
            {r["activity_uid"] for r in state["scenario"]["activities"]},
        )
        baseline_dispositions = {
            row["activity_uid"]: (
                row["disposition"], row["exclusion_code"], tuple(row["assumptions"])
            )
            for row in state["baseline"]["activities"]
        }
        scenario_dispositions = {
            row["activity_uid"]: (
                row["disposition"], row["exclusion_code"], tuple(row["assumptions"])
            )
            for row in state["scenario"]["activities"]
        }
        self.assertEqual(scenario_dispositions, baseline_dispositions)

        scenario_version = state["current_version_id"]
        scenario_fingerprint = state["scenario"]["fingerprint"]
        with self.client() as restarted:
            recovered = restarted.get(f"/api/projects/{project}/planner").json()
        self.assertEqual(recovered["current_version_id"], scenario_version)
        self.assertEqual(recovered["scenario"]["fingerprint"], scenario_fingerprint)
        self.assertEqual(
            self.activity(recovered, "Execute inspection", "scenario")["early_start"],
            scenario_downstream["early_start"],
        )

        with psycopg.connect(self.url) as conn:
            versions = conn.execute(
                "SELECT id, kind, canonical_hash FROM schedule_versions WHERE project_id=%s "
                "ORDER BY sequence",
                (uuid.UUID(project),),
            ).fetchall()
            lineage = conn.execute(
                "SELECT * FROM scenario_changes WHERE project_id=%s",
                (uuid.UUID(project),),
            ).fetchone()
            calculations = conn.execute(
                "SELECT version_id FROM schedule_calculations WHERE project_id=%s",
                (uuid.UUID(project),),
            ).fetchall()
        self.assertEqual([row["kind"] for row in versions], ["baseline", "scenario"])
        self.assertEqual(versions[0]["canonical_hash"], imported["canonical_hash"])
        self.assertEqual(lineage["baseline_version_id"], uuid.UUID(imported["version_id"]))
        self.assertEqual(lineage["scenario_version_id"], uuid.UUID(scenario_version))
        self.assertEqual(
            {row["version_id"] for row in calculations},
            {uuid.UUID(imported["version_id"]), uuid.UUID(scenario_version)},
        )
        self.assertEqual(
            state["baseline"]["calculation_id"], baseline_summary["calculation_id"]
        )
        with self.assertRaises(psycopg.errors.CheckViolation):
            with psycopg.connect(self.url) as conn:
                conn.execute(
                    "UPDATE scenario_changes SET after_seconds=after_seconds+1 WHERE id=%s",
                    (lineage["id"],),
                )
        with self.assertRaises(psycopg.errors.CheckViolation):
            with psycopg.connect(self.url) as conn:
                conn.execute("DELETE FROM scenario_changes WHERE id=%s", (lineage["id"],))

    def test_stale_edit_reset_and_export_contract(self):
        client, project, imported, _ = self.prepared("conflict")
        initial = client.get(f"/api/projects/{project}/planner").json()
        target = initial["eligible_activities"][0]
        edit = {
            "expected_version_id": initial["current_version_id"],
            "activity_uid": target["activity_uid"],
            "planned_duration_seconds": target["planned_duration_seconds"] + 3600,
        }
        created = client.post(f"/api/projects/{project}/scenario", json=edit)
        self.assertEqual(created.status_code, 201, created.text)
        scenario = created.json()
        self.assertEqual(
            client.post(f"/api/projects/{project}/scenario", json=edit).status_code,
            409,
        )

        exported = client.get(f"/api/projects/{project}/scenario/export")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("attachment;", exported.headers["content-disposition"])
        body = exported.json()
        self.assertEqual(body["format"], "sto-prototype-scenario-state-1")
        self.assertEqual(body["baseline_version_id"], imported["version_id"])
        self.assertEqual(body["scenario_version_id"], scenario["current_version_id"])
        self.assertEqual(
            body["calculation"]["fingerprint"], scenario["scenario"]["fingerprint"]
        )
        self.assertEqual(body["change"]["activity_uid"], target["activity_uid"])
        self.assertTrue(body["activities"])
        self.assertIn("scheduled", body["calculation"]["dispositions"])

        reset = client.post(
            f"/api/projects/{project}/scenario/reset",
            json={"expected_version_id": scenario["current_version_id"]},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        reset_state = reset.json()
        self.assertEqual(reset_state["current_kind"], "baseline")
        self.assertEqual(reset_state["current_version_id"], imported["version_id"])
        self.assertIsNone(reset_state["scenario"])
        self.assertIsNone(reset_state["change"])
        stale_reset = client.post(
            f"/api/projects/{project}/scenario/reset",
            json={"expected_version_id": scenario["current_version_id"]},
        )
        self.assertEqual(stale_reset.status_code, 409)
        with self.client() as restarted:
            recovered = restarted.get(f"/api/projects/{project}/planner").json()
        self.assertEqual(recovered["current_kind"], "baseline")
        self.assertEqual(
            recovered["baseline"]["fingerprint"], reset_state["baseline"]["fingerprint"]
        )

    def test_invalid_unsupported_and_cross_project_edits_are_controlled(self):
        client, first, _, _ = self.prepared("first")
        second_client, second, _, _ = self.prepared("second")
        first_state = client.get(f"/api/projects/{first}/planner").json()
        second_state = second_client.get(f"/api/projects/{second}/planner").json()
        first_document = client.get(
            f"/api/projects/{first}/schedule", params={"include": "document"}
        ).json()["document"]
        milestone = next(
            row for row in first_document["activities"] if row["name"] == "Work complete"
        )

        invalid = client.post(
            f"/api/projects/{first}/scenario",
            json={
                "expected_version_id": first_state["current_version_id"],
                "activity_uid": first_state["eligible_activities"][0]["activity_uid"],
                "planned_duration_seconds": 0,
            },
        )
        self.assertEqual(invalid.status_code, 422)
        unsupported = client.post(
            f"/api/projects/{first}/scenario",
            json={
                "expected_version_id": first_state["current_version_id"],
                "activity_uid": milestone["uid"],
                "planned_duration_seconds": 3600,
            },
        )
        self.assertEqual(unsupported.status_code, 422)
        self.assertEqual(unsupported.json()["detail"]["code"], "ACTIVITY_NOT_LEAF_TASK")
        isolated = client.post(
            f"/api/projects/{first}/scenario",
            json={
                "expected_version_id": first_state["current_version_id"],
                "activity_uid": str(uuid.uuid4()),
                "planned_duration_seconds": 3600,
            },
        )
        self.assertEqual(isolated.status_code, 422)
        self.assertEqual(isolated.json()["detail"]["code"], "ACTIVITY_NOT_FOUND")
        self.assertEqual(
            second_client.get(f"/api/projects/{second}/planner").json()["current_kind"],
            "baseline",
        )

    def test_reimport_makes_an_old_scenario_historic(self):
        client, project, _, _ = self.prepared("reimport")
        initial = client.get(f"/api/projects/{project}/planner").json()
        target = initial["eligible_activities"][0]
        scenario = client.post(
            f"/api/projects/{project}/scenario",
            json={
                "expected_version_id": initial["current_version_id"],
                "activity_uid": target["activity_uid"],
                "planned_duration_seconds": target["planned_duration_seconds"] + 3600,
            },
        ).json()
        with FIXTURE.open("rb") as handle:
            imported = client.post(
                f"/api/projects/{project}/imports",
                files={"file": (FIXTURE.name, handle, "application/xml")},
            )
        self.assertEqual(imported.status_code, 201, imported.text)
        state = client.get(f"/api/projects/{project}/planner").json()
        self.assertEqual(state["current_kind"], "baseline")
        self.assertEqual(state["current_version_id"], imported.json()["version_id"])
        self.assertIsNone(state["scenario"])
        with psycopg.connect(self.url) as conn:
            old = conn.execute(
                "SELECT 1 FROM schedule_versions WHERE id=%s AND kind='scenario'",
                (uuid.UUID(scenario["current_version_id"]),),
            ).fetchone()
        self.assertIsNotNone(old)


if __name__ == "__main__":
    unittest.main()
