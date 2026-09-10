"""PL14's persisted duration scenario, through the real API and PostgreSQL."""

from __future__ import annotations

import os
import secrets
import tempfile
import threading
import time
import unittest
import uuid
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
    from psycopg.rows import dict_row
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

        with psycopg.connect(self.url, row_factory=dict_row) as conn:
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

    def test_planned_duration_can_change_to_an_unchanged_remaining_duration(self):
        """A valid unstarted activity may already have a shorter remaining span."""

        client = self.client()
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        project = client.post("/api/projects", json={"name": "remaining"}).json()["id"]
        original = b"<Duration>PT4H0M0S</Duration><DurationFormat>5</DurationFormat>"
        changed = b"<Duration>PT10H0M0S</Duration><DurationFormat>5</DurationFormat>"
        data = FIXTURE.read_bytes().replace(original, changed, 1)
        self.assertNotEqual(data, FIXTURE.read_bytes())
        imported = client.post(
            f"/api/projects/{project}/imports",
            files={"file": (FIXTURE.name, data, "application/xml")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        calculated = client.post(f"/api/projects/{project}/calculations")
        self.assertEqual(calculated.status_code, 201, calculated.text)
        initial = client.get(f"/api/projects/{project}/planner").json()
        target = next(
            row for row in initial["eligible_activities"]
            if row["name"] == "Isolate equipment"
        )
        self.assertEqual(target["planned_duration_seconds"], 10 * 3600)

        response = client.post(
            f"/api/projects/{project}/scenario",
            json={
                "expected_version_id": initial["current_version_id"],
                "activity_uid": target["activity_uid"],
                "planned_duration_seconds": 4 * 3600,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        change = response.json()["change"]
        self.assertEqual(change["before_seconds"], 10 * 3600)
        self.assertEqual(change["after_seconds"], 4 * 3600)
        self.assertEqual(change["remaining_before_seconds"], 4 * 3600)
        self.assertEqual(change["remaining_after_seconds"], 4 * 3600)

    def test_zero_remaining_duration_is_a_controlled_unsupported_target(self):
        client = self.client()
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        project = client.post("/api/projects", json={"name": "zero-remaining"}).json()["id"]
        data = FIXTURE.read_bytes().replace(
            b"<RemainingDuration>PT4H0M0S</RemainingDuration>",
            b"<RemainingDuration>PT0H0M0S</RemainingDuration>",
            1,
        )
        imported = client.post(
            f"/api/projects/{project}/imports",
            files={"file": (FIXTURE.name, data, "application/xml")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        calculated = client.post(f"/api/projects/{project}/calculations")
        self.assertEqual(calculated.status_code, 201, calculated.text)
        initial = client.get(f"/api/projects/{project}/planner").json()
        target = self.activity(initial, "Isolate equipment")
        self.assertNotIn(
            target["activity_uid"],
            {row["activity_uid"] for row in initial["eligible_activities"]},
        )

        response = client.post(
            f"/api/projects/{project}/scenario",
            json={
                "expected_version_id": initial["current_version_id"],
                "activity_uid": target["activity_uid"],
                "planned_duration_seconds": 8 * 3600,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["detail"]["code"], "ACTIVITY_REMAINING_DURATION_ZERO"
        )

    def test_reset_route_rejects_a_baseline_superseded_before_response(self):
        client, project, _, _ = self.prepared("superseded-reset-response")
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
        workspace = client.app.state.workspace
        original_state = workspace.planner_state

        def import_then_read(project_id):
            workspace.import_file(
                project_id,
                filename="concurrent-reset.xml",
                data=FIXTURE.read_bytes(),
            )
            return original_state(project_id)

        with patch.object(workspace, "planner_state", side_effect=import_then_read):
            response = client.post(
                f"/api/projects/{project}/scenario/reset",
                json={"expected_version_id": scenario["current_version_id"]},
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("superseded", response.text)
        state = client.get(f"/api/projects/{project}/planner").json()
        self.assertEqual(state["current_kind"], "baseline")
        self.assertNotEqual(state["current_version_id"], initial["current_version_id"])
        self.assertIsNone(state["baseline"])
        self.assertIsNone(state["scenario"])

    def test_planner_reads_baseline_and_scenario_before_a_concurrent_import(self):
        client, project, imported, _ = self.prepared("planner-read-snapshot")
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
        workspace = client.app.state.workspace
        from sto.persistence import repositories as repo

        original_head_version = repo.head_version
        baseline_read = threading.Event()
        importer_started = threading.Event()
        read_result = []
        failures = []

        def observed_head_version(conn, **kwargs):
            result = original_head_version(conn, **kwargs)
            if (
                threading.current_thread().name == "planner-read"
                and kwargs["kind"] == "baseline"
                and kwargs["with_document"]
            ):
                baseline_read.set()
                if not importer_started.wait(2):
                    raise AssertionError("concurrent importer did not start")
                time.sleep(0.1)
            return result

        def read_planner():
            try:
                read_result.append(workspace.planner_state(uuid.UUID(project)))
            except BaseException as error:  # preserve worker failure for the test thread
                failures.append(error)

        def import_new_baseline():
            try:
                if not baseline_read.wait(2):
                    raise AssertionError("planner did not read its baseline")
                importer_started.set()
                workspace.import_file(
                    uuid.UUID(project),
                    filename="concurrent-planner-read.xml",
                    data=FIXTURE.read_bytes(),
                )
            except BaseException as error:  # preserve worker failure for the test thread
                failures.append(error)

        with patch.object(repo, "head_version", side_effect=observed_head_version):
            reader = threading.Thread(target=read_planner, name="planner-read")
            importer = threading.Thread(target=import_new_baseline, name="planner-import")
            reader.start()
            importer.start()
            reader.join(10)
            importer.join(10)
        self.assertFalse(reader.is_alive() or importer.is_alive(), "concurrent read hung")
        self.assertEqual(failures, [])
        self.assertEqual(len(read_result), 1)
        observed = read_result[0]
        self.assertEqual(str(observed["baseline_version_id"]), imported["version_id"])
        self.assertEqual(
            str(observed["change"]["baseline_version_id"]), imported["version_id"]
        )
        self.assertEqual(
            str(observed["current_version_id"]), scenario["current_version_id"]
        )
        current = client.get(f"/api/projects/{project}/planner").json()
        self.assertEqual(current["current_kind"], "baseline")
        self.assertNotEqual(current["baseline_version_id"], imported["version_id"])

    def test_scenario_route_rejects_a_result_superseded_before_response(self):
        client, project, _, _ = self.prepared("superseded-response")
        initial = client.get(f"/api/projects/{project}/planner").json()
        target = initial["eligible_activities"][0]
        workspace = client.app.state.workspace
        original_state = workspace.planner_state

        def import_then_read(project_id):
            workspace.import_file(
                project_id,
                filename="concurrent.xml",
                data=FIXTURE.read_bytes(),
            )
            return original_state(project_id)

        with patch.object(workspace, "planner_state", side_effect=import_then_read):
            response = client.post(
                f"/api/projects/{project}/scenario",
                json={
                    "expected_version_id": initial["current_version_id"],
                    "activity_uid": target["activity_uid"],
                    "planned_duration_seconds": (
                        target["planned_duration_seconds"] + 3600
                    ),
                },
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("superseded", response.text)
        state = client.get(f"/api/projects/{project}/planner").json()
        self.assertEqual(state["current_kind"], "baseline")
        self.assertIsNone(state["scenario"])

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

    def test_database_refuses_a_named_baseline_that_is_not_the_scenario_parent(self):
        client, project, imported, _ = self.prepared("lineage-parent")
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
        alternate_baseline = uuid.uuid4()
        bad_scenario = uuid.uuid4()
        bad_change = uuid.uuid4()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with psycopg.connect(self.url) as conn:
                next_sequence = conn.execute(
                    "SELECT max(sequence) + 1 FROM schedule_versions WHERE project_id=%s",
                    (uuid.UUID(project),),
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO schedule_versions
                      (id, project_id, kind, sequence, parent_id, canonical_hash,
                       schema_version, engine_profile, cause_type, cause_id,
                       document, identity_map)
                    SELECT %s, project_id, 'baseline', %s, id, canonical_hash,
                           schema_version, engine_profile, 'import', NULL,
                           document, identity_map
                    FROM schedule_versions WHERE id=%s
                    """,
                    (alternate_baseline, next_sequence, uuid.UUID(imported["version_id"])),
                )
                conn.execute(
                    """
                    INSERT INTO schedule_versions
                      (id, project_id, kind, sequence, parent_id, canonical_hash,
                       schema_version, engine_profile, cause_type, cause_id,
                       document, identity_map)
                    SELECT %s, project_id, 'scenario', %s, %s, canonical_hash,
                           schema_version, engine_profile, 'planner_edit', %s,
                           document, identity_map
                    FROM schedule_versions WHERE id=%s
                    """,
                    (
                        bad_scenario,
                        next_sequence + 1,
                        uuid.UUID(imported["version_id"]),
                        bad_change,
                        uuid.UUID(scenario["current_version_id"]),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO scenario_changes
                      (id, project_id, baseline_version_id, scenario_version_id,
                       activity_uid, before_seconds, after_seconds)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        bad_change,
                        uuid.UUID(project),
                        alternate_baseline,
                        bad_scenario,
                        uuid.UUID(target["activity_uid"]),
                        target["planned_duration_seconds"],
                        target["planned_duration_seconds"] + 3600,
                    ),
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
        boolean = client.post(
            f"/api/projects/{first}/scenario",
            json={
                "expected_version_id": first_state["current_version_id"],
                "activity_uid": first_state["eligible_activities"][0]["activity_uid"],
                "planned_duration_seconds": True,
            },
        )
        self.assertEqual(boolean.status_code, 422)
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
