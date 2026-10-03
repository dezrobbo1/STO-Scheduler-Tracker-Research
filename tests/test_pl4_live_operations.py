"""PL4 accepted operations, transactional publication, restart and replay."""

from __future__ import annotations

import os
import asyncio
import secrets
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sto.core.execution import ExecutionChange

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/synthetic-workspace-chain.mspdi.xml"
ADMIN_URL = os.environ.get("STO_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres")
REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"

try:
    import psycopg
    from fastapi.testclient import TestClient
except ImportError as error:
    if REQUIRE_DB:
        raise RuntimeError("STO_REQUIRE_DB=1 requires the API and test extras") from error
    psycopg = None


def reachable() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            return True
    except psycopg.OperationalError as error:
        if REQUIRE_DB:
            raise RuntimeError(f"STO_REQUIRE_DB=1 but PostgreSQL is unreachable: {error}") from error
        return False


class SemanticIdentityTests(unittest.TestCase):
    @unittest.skipUnless(psycopg is not None, "PL4 API extras unavailable")
    def test_binding_includes_actor_project_base_and_every_execution_fact(self):
        from sto.core.hashing import canonical_sha256
        from sto.scheduling.live_operations import ExecutionOperation, semantic_payload

        project, actor, base, activity = (uuid.uuid4() for _ in range(4))
        change = ExecutionChange(activity, "a" * 64, datetime(2026, 1, 5, 9),
                                 remaining_seconds=3600)
        first = ExecutionOperation(uuid.uuid4(), base, change)
        initial = semantic_payload(project, actor, first)
        self.assertEqual(initial, semantic_payload(project, actor,
                         ExecutionOperation(uuid.uuid4(), base, change)))
        self.assertNotIn("operation_id", initial)
        variants = [
            semantic_payload(uuid.uuid4(), actor, first),
            semantic_payload(project, uuid.uuid4(), first),
            semantic_payload(project, actor, ExecutionOperation(first.operation_id,
                uuid.uuid4(), change)),
            semantic_payload(project, actor, ExecutionOperation(first.operation_id,
                base, ExecutionChange(activity, change.expected_hash,
                                      change.actual_start, remaining_seconds=1800))),
        ]
        self.assertTrue(all(canonical_sha256(row) != canonical_sha256(initial)
                            for row in variants))


@unittest.skipUnless(reachable(), "PostgreSQL unavailable; STO_REQUIRE_DB=1 makes this fail")
class LiveOperationDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sto.persistence.db import connect
        from tests.auth_fixture import AuthTestContext

        cls.dbname = f"sto_pl4_{secrets.token_hex(4)}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{cls.dbname}"')
        cls.url = ADMIN_URL.rsplit("/", 1)[0] + "/" + cls.dbname
        with psycopg.connect(cls.url) as conn:
            for path in sorted((ROOT / "infra/migrations").glob("V*.sql")):
                conn.execute(path.read_text())
            conn.commit()
        cls.connect = staticmethod(lambda url=cls.url: connect(url))
        cls.temp = tempfile.TemporaryDirectory()
        cls.auth = AuthTestContext(connect=cls.connect, username="pl4-author")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{cls.dbname}" WITH (FORCE)')

    def client(self):
        from sto.scheduling.working_schedule import Workspace
        return self.auth.client(Workspace(connect=self.connect,
                                          source_dir=Path(self.temp.name)))

    def prepared(self, client):
        project = client.post("/api/projects", json={"name": "PL4 synthetic"}).json()["id"]
        imported = client.post(
            f"/api/projects/{project}/imports",
            files={"file": (SOURCE.name, SOURCE.read_bytes(), "application/xml")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        calculated = client.post(f"/api/projects/{project}/calculations")
        self.assertEqual(calculated.status_code, 201, calculated.text)
        planner = client.get(f"/api/projects/{project}/planner").json()
        uids = [row["activity_uid"] for row in planner["eligible_activities"]]
        self.assertGreaterEqual(len(uids), 2)
        return project, imported.json(), uids

    def command(self, client, project, base, uid, *, operation_id=None, remaining=3600):
        return {
            "operation_id": str(operation_id or uuid.uuid4()),
            "expected_version_id": base["version_id"] if "version_id" in base else base["result_version_id"],
            "expected_hash": base["canonical_hash"], "activity_uid": uid,
            "actual_start": "2026-01-05T09:00:00", "remaining_seconds": remaining,
        }

    def test_accept_retry_conflict_catchup_restart_and_replay(self):
        from sto.scheduling.live_operations import replay
        from sto.persistence import repositories as repo

        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            self.assertEqual(baseline["canonical_hash"],
                             "9c783428c52d85156a1a90e848d276cd8a3121a59d23cff912cd46d003be685c")
            url = f"/api/projects/{project}/execution-operations"
            first_body = self.command(client, project, baseline, uids[0],
                                      operation_id=uuid.uuid5(uuid.NAMESPACE_URL, "sto/pl4/replay/first"))
            first = client.post(url, json=first_body)
            self.assertEqual(first.status_code, 201, first.text)
            first_receipt = first.json()
            self.assertEqual(first_receipt["server_sequence"], 1)
            with patch("sto.scheduling.live_operations.apply_execution",
                       side_effect=AssertionError("retry recalculated")):
                retry = client.post(url, json=first_body)
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertEqual(retry.json(), first_receipt)
            conflict = client.post(url, json={**first_body, "remaining_seconds": 1800})
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["detail"]["code"], "LIVE_OPERATION_ID_CONFLICT")
            stale = self.command(client, project, baseline, uids[1])
            self.assertEqual(client.post(url, json=stale).json()["detail"]["code"],
                             "LIVE_STALE_HEAD")
            second_body = self.command(client, project, first_receipt, uids[1],
                                       operation_id=uuid.uuid5(uuid.NAMESPACE_URL, "sto/pl4/replay/second"))
            second = client.post(url, json=second_body)
            self.assertEqual(second.status_code, 201, second.text)
            self.assertEqual(second.json()["server_sequence"], 2)
            page = client.get(f"/api/projects/{project}/changes",
                              params={"after": 0, "limit": 1}).json()
            self.assertEqual([e["operation_id"] for e in page["events"]],
                             [first_body["operation_id"]])
            self.assertTrue(page["has_more"])
            next_page = client.get(f"/api/projects/{project}/changes",
                                   params={"after": page["next_cursor"]}).json()
            self.assertEqual(next_page["events"][0]["operation_id"],
                             second_body["operation_id"])
            self.assertEqual(next_page["next_cursor"], 2)
            self.assertFalse(next_page["has_more"])
            self.assertEqual(client.get(f"/api/projects/{project}/changes",
                                        params={"after": 3}).status_code, 409)
            with self.connect() as conn:
                head = repo.head_version(conn, project_id=uuid.UUID(project),
                                         kind="live_working", with_document=False)
                versions = repo.list_versions(conn, project_id=uuid.UUID(project))
            self.assertEqual(head["id"], uuid.UUID(second.json()["result_version_id"]))
            self.assertEqual([v["cause_type"] for v in versions[-2:]],
                             ["progress", "progress"])

        with self.client() as restarted:
            receipt = restarted.get(f"{url}/{first_body['operation_id']}")
            self.assertEqual(receipt.status_code, 200, receipt.text)
            self.assertEqual(receipt.json(), first_receipt)
            self.assertEqual(restarted.post(url, json=second_body).status_code, 200)
            self.assertEqual(restarted.get(f"/api/projects/{project}/live").json()["canonical_hash"],
                             second.json()["canonical_hash"])
            proof = replay(restarted.app.state.workspace, uuid.UUID(project))
            self.assertEqual(proof["baseline_hash"], baseline["canonical_hash"])
            self.assertEqual(proof["operation_ids"],
                             [uuid.UUID(first_body["operation_id"]), uuid.UUID(second_body["operation_id"])])
            self.assertEqual(proof["head_hash"], second.json()["canonical_hash"])
            self.assertEqual(proof["replay_hash"], proof["head_hash"])
            self.assertEqual(proof["head_hash"],
                             "2798f4726ec9725ff5fa1c94afc4874cb3217836e844b8c9e4b47e9336233383")
            child = subprocess.run(
                [sys.executable, "-c",
                 "import sys,uuid; from sto.persistence.db import connect; "
                 "from sto.scheduling.working_schedule import Workspace; "
                 "from sto.scheduling.live_operations import replay; "
                 "print(replay(Workspace(connect=connect), uuid.UUID(sys.argv[1]))['replay_hash'])",
                 project],
                cwd=ROOT, env={**os.environ, "STO_DATABASE_URL": self.url,
                               "PYTHONPATH": str(ROOT / "src")},
                text=True, capture_output=True, check=True,
            )
            self.assertEqual(child.stdout.strip(), proof["head_hash"])
            if os.environ.get("STO_PL4_RECORD_REPLAY") == "1":
                print("PL4 replay evidence:", proof)

    def test_rollback_domain_refusal_and_lost_ack_recovery(self):
        from sto.persistence import repositories as repo

        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            url = f"/api/projects/{project}/execution-operations"
            body = self.command(client, project, baseline, uids[0])
            refusal = client.post(url, json={**body, "remaining_seconds": 0})
            self.assertEqual(refusal.status_code, 422, refusal.text)
            self.assertEqual(refusal.json()["detail"]["code"],
                             "EXECUTION_IN_PROGRESS_REMAINING_ZERO")
            with patch("sto.scheduling.live_operations.repo.insert_live_operation",
                       side_effect=RuntimeError("injected before commit")):
                with self.assertRaisesRegex(RuntimeError, "injected before commit"):
                    client.post(url, json=body)
            original_set_head = repo.set_head

            def fail_after_row(conn, *, project_id, kind, version_id):
                if kind == "live_working":
                    raise RuntimeError("operation row inserted but transaction aborted")
                return original_set_head(conn, project_id=project_id, kind=kind,
                                         version_id=version_id)

            with patch("sto.scheduling.live_operations.repo.set_head",
                       side_effect=fail_after_row):
                with self.assertRaisesRegex(RuntimeError, "transaction aborted"):
                    client.post(url, json=body)
            with patch("sto.scheduling.live_operations._credential_still_valid",
                       side_effect=[True, False]):
                expired = client.post(url, json=body)
            self.assertEqual(expired.status_code, 401, expired.text)
            with self.connect() as conn:
                self.assertEqual(repo.live_cursor(conn, uuid.UUID(project)), 0)
                self.assertIsNone(repo.head_version(conn, project_id=uuid.UUID(project),
                                                     kind="live_working", with_document=False))
                self.assertEqual(len(repo.list_versions(conn, project_id=uuid.UUID(project))), 1)
            from sto.scheduling.live_operations import submit
            captured = []

            def commit_then_drop(workspace, project_id, access, operation, *, auth_now):
                captured.append(submit(workspace, project_id, access, operation,
                                       auth_now=auth_now)[0])
                raise RuntimeError("lost response")

            # The original call commits; the response is lost after commit.
            with patch("sto.api.app.submit_live", side_effect=commit_then_drop):
                with self.assertRaisesRegex(RuntimeError, "lost response"):
                    client.post(url, json=body)
            recovered = client.post(url, json=body)
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()["server_sequence"], 1)
            self.assertEqual(recovered.json()["operation_id"], str(captured[0]["operation_id"]))

    def test_concurrent_duplicates_and_project_authority(self):
        from tests.auth_fixture import AuthTestContext
        from sto.persistence import repositories as repo

        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            body = self.command(client, project, baseline, uids[0])
            url = f"/api/projects/{project}/execution-operations"
            from sto.api.app import create_app
            unauth = TestClient(create_app(client.app.state.workspace, self.auth.service))
            self.assertEqual(unauth.post(url, json=body).status_code, 401)
            outsider = AuthTestContext(connect=self.connect, username=f"pl4-outsider-{uuid.uuid4().hex[:6]}")
            with outsider.client(client.app.state.workspace) as other:
                self.assertEqual(other.post(url, json=body).status_code, 404)
                grant = client.post(f"/api/projects/{project}/memberships",
                                    json={"user_id": str(outsider.user["id"]), "role": "viewer"})
                self.assertEqual(grant.status_code, 200, grant.text)
                self.assertEqual(other.post(url, json=body).status_code, 403)
                self.assertEqual(other.get(f"/api/projects/{project}/changes").status_code, 200)
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(lambda _: client.post(url, json=body), range(2)))
            self.assertEqual(sorted(r.status_code for r in outcomes), [200, 201])
            self.assertEqual(outcomes[0].json(), outcomes[1].json())
            with self.connect() as conn:
                self.assertEqual(repo.live_cursor(conn, uuid.UUID(project)), 1)
                self.assertEqual(len(repo.list_versions(conn, project_id=uuid.UUID(project))), 2)

    def test_distinct_concurrent_commands_cannot_overwrite_a_stale_head(self):
        from sto.persistence import repositories as repo

        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            url = f"/api/projects/{project}/execution-operations"
            proposals = [self.command(client, project, baseline, uid) for uid in uids[:2]]
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(lambda body: client.post(url, json=body),
                                             proposals))
            self.assertEqual(sorted(row.status_code for row in outcomes), [201, 409])
            self.assertEqual(next(row for row in outcomes if row.status_code == 409)
                             .json()["detail"]["code"], "LIVE_STALE_HEAD")
            with self.connect() as conn:
                self.assertEqual(repo.live_cursor(conn, uuid.UUID(project)), 1)

    def test_operation_identity_is_project_scoped_and_actor_bound(self):
        from tests.auth_fixture import AuthTestContext

        with self.client() as client:
            first_project, first_baseline, first_uids = self.prepared(client)
            second_project, second_baseline, second_uids = self.prepared(client)
            operation_id = uuid.uuid4()
            first = self.command(client, first_project, first_baseline, first_uids[0],
                                 operation_id=operation_id)
            second = self.command(client, second_project, second_baseline, second_uids[0],
                                  operation_id=operation_id)
            first_url = f"/api/projects/{first_project}/execution-operations"
            second_url = f"/api/projects/{second_project}/execution-operations"
            self.assertEqual(client.post(first_url, json=first).status_code, 201)
            self.assertEqual(client.post(second_url, json=second).status_code, 201)
            other_auth = AuthTestContext(connect=self.connect,
                                         username=f"pl4-other-{uuid.uuid4().hex[:6]}")
            grant = client.post(f"/api/projects/{first_project}/memberships",
                                json={"user_id": str(other_auth.user["id"]), "role": "planner"})
            self.assertEqual(grant.status_code, 200, grant.text)
            with other_auth.client(client.app.state.workspace) as other:
                reuse = other.post(first_url, json=first)
                self.assertEqual(reuse.status_code, 409, reuse.text)
                self.assertEqual(reuse.json()["detail"]["code"],
                                 "LIVE_OPERATION_ID_CONFLICT")

    def test_start_remaining_and_finish_are_all_applied_by_s7(self):
        from sto.scheduling.live_operations import replay

        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            url = f"/api/projects/{project}/execution-operations"
            start = client.post(url, json=self.command(client, project, baseline, uids[0]))
            self.assertEqual(start.status_code, 201, start.text)
            remainder = client.post(url, json={
                "operation_id": str(uuid.uuid4()),
                "expected_version_id": start.json()["result_version_id"],
                "expected_hash": start.json()["canonical_hash"],
                "activity_uid": uids[0], "remaining_seconds": 1800,
            })
            self.assertEqual(remainder.status_code, 201, remainder.text)
            finish = client.post(url, json={
                "operation_id": str(uuid.uuid4()),
                "expected_version_id": remainder.json()["result_version_id"],
                "expected_hash": remainder.json()["canonical_hash"],
                "activity_uid": uids[0], "actual_finish": "2026-01-05T10:00:00",
                "remaining_seconds": 0,
            })
            self.assertEqual(finish.status_code, 201, finish.text)
            self.assertEqual(finish.json()["server_sequence"], 3)
            stored = client.app.state.workspace.read_calculation(
                uuid.UUID(project), kind="live_working")
            self.assertEqual(stored.result.by_uid()[uuid.UUID(uids[0])].state,
                             "complete")
            proof = replay(client.app.state.workspace, uuid.UUID(project))
            self.assertEqual(proof["replay_hash"], finish.json()["canonical_hash"])

    def test_reimport_supersedes_live_head_and_keeps_history(self):
        from sto.persistence import repositories as repo

        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            url = f"/api/projects/{project}/execution-operations"
            body = self.command(client, project, baseline, uids[0])
            self.assertEqual(client.post(url, json=body).status_code, 201)
            imported = client.post(
                f"/api/projects/{project}/imports",
                files={"file": (SOURCE.name, SOURCE.read_bytes(), "application/xml")},
            )
            self.assertEqual(imported.status_code, 201, imported.text)
            with self.connect() as conn:
                self.assertIsNone(repo.head_version(conn, project_id=uuid.UUID(project),
                                                     kind="live_working", with_document=False))
                self.assertEqual(repo.live_cursor(conn, uuid.UUID(project)), 1)
            self.assertEqual(client.get(f"/api/projects/{project}/live").json()["version_id"],
                             imported.json()["version_id"])

    def test_corrupt_live_head_is_refused_and_reported_after_restart(self):
        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            accepted = client.post(
                f"/api/projects/{project}/execution-operations",
                json=self.command(client, project, baseline, uids[0]),
            )
            self.assertEqual(accepted.status_code, 201, accepted.text)
            with self.connect() as conn:
                conn.execute(
                    "UPDATE schedule_versions SET canonical_hash = %s WHERE id = %s",
                    ("0" * 64, uuid.UUID(accepted.json()["result_version_id"])),
                )
                conn.commit()
        with self.client() as restarted:
            self.assertIn(uuid.UUID(project), restarted.app.state.workspace.integrity_failures)
            self.assertEqual(restarted.get(f"/api/projects/{project}/live").status_code, 500)

    def test_sse_only_emits_committed_rows_and_reconnect_catches_up(self):
        from fastapi import Request
        from sto.api.auth import ProjectAccess

        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            url = f"/api/projects/{project}/execution-operations"
            body = self.command(client, project, baseline, uids[0])
            stream_route = next(route for route in client.app.routes
                                if getattr(route, "path", "") ==
                                "/api/projects/{project_id}/changes/stream")
            name = self.auth.service.config.cookie_name
            raw = client.cookies.get(name)
            actor = self.auth.service.authenticate_session(raw)

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            request = Request({
                "type": "http", "method": "GET", "scheme": "http",
                "path": f"/api/projects/{project}/changes/stream",
                "headers": [(b"cookie", f"{name}={raw}".encode())],
                "app": client.app,
            }, receive)

            async def exercise():
                response = await stream_route.endpoint(
                    request, uuid.UUID(project), 0,
                    ProjectAccess(actor, uuid.UUID(project), "admin"),
                    client.app.state.workspace,
                )
                self.assertEqual(response.media_type, "text/event-stream")
                stream = response.body_iterator
                self.assertIn("keepalive", await anext(stream))
                with patch("sto.scheduling.live_operations.repo.insert_live_operation",
                           side_effect=RuntimeError("uncommitted")):
                    with self.assertRaisesRegex(RuntimeError, "uncommitted"):
                        client.post(url, json=body)
                self.assertIn("keepalive", await anext(stream))
                accepted = client.post(url, json=body)
                self.assertEqual(accepted.status_code, 201, accepted.text)
                event = await anext(stream)
                self.assertIn("id: 1\nevent: execution\n", event)
                self.assertIn(body["operation_id"], event)
                await stream.aclose()
                return accepted.json()

            accepted = asyncio.run(exercise())
            missed = client.get(f"/api/projects/{project}/changes",
                                params={"after": 0}).json()
            self.assertEqual(missed["events"][0], accepted)
            self.assertEqual(missed["next_cursor"], 1)

    def test_v008_upgrades_an_existing_baseline_without_rewriting_history(self):
        name = f"sto_pl4_upgrade_{secrets.token_hex(4)}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{name}"')
        url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
        try:
            paths = sorted((ROOT / "infra/migrations").glob("V*.sql"))
            with psycopg.connect(url) as conn:
                for path in paths[:-1]:
                    conn.execute(path.read_text())
                project = conn.execute(
                    "INSERT INTO projects(name) VALUES ('upgrade fixture') RETURNING id"
                ).fetchone()[0]
                conn.commit()
            with psycopg.connect(url) as conn:
                conn.execute(paths[-1].read_text())
                self.assertEqual(conn.execute("SELECT count(*) FROM projects").fetchone()[0], 1)
                self.assertEqual(conn.execute(
                    "SELECT count(*) FROM live_execution_operations WHERE project_id = %s",
                    (project,),
                ).fetchone()[0], 0)
                conn.commit()
        finally:
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')

    def test_revoked_credential_between_dependency_and_commit_is_refused(self):
        from sto.persistence import auth_repositories as auth_repo
        from sto.scheduling.live_operations import submit

        with self.client() as client:
            project, baseline, uids = self.prepared(client)
            body = self.command(client, project, baseline, uids[0])

            def revoked_submit(workspace, project_id, access, operation, *, auth_now):
                with self.connect() as conn:
                    auth_repo.revoke_session(conn, access.actor.session_id)
                    conn.commit()
                return submit(workspace, project_id, access, operation, auth_now=auth_now)

            with patch("sto.api.app.submit_live", side_effect=revoked_submit):
                refused = client.post(f"/api/projects/{project}/execution-operations",
                                      json=body)
            self.assertEqual(refused.status_code, 401, refused.text)
            with self.connect() as conn:
                from sto.persistence import repositories as repo
                self.assertEqual(repo.live_cursor(conn, uuid.UUID(project)), 0)
