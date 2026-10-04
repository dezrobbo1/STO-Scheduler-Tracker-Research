"""Bounded communication/photo architecture trial on PL4's ordered substrate."""

from __future__ import annotations

import os
import secrets
import tempfile
import unittest
import uuid
import hashlib
from unittest.mock import patch
from pathlib import Path

from tests.test_pl4_live_operations import ADMIN_URL, ROOT, SOURCE, reachable

try:
    import psycopg
except ImportError:
    psycopg = None


@unittest.skipUnless(reachable(), "PostgreSQL unavailable; STO_REQUIRE_DB=1 makes this fail")
class TrialDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sto.persistence.db import connect
        from tests.auth_fixture import AuthTestContext

        cls.dbname = f"sto_pl5_{secrets.token_hex(4)}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{cls.dbname}"')
        cls.url = ADMIN_URL.rsplit("/", 1)[0] + "/" + cls.dbname
        with psycopg.connect(cls.url) as conn:
            for path in sorted((ROOT / "infra/migrations").glob("V*.sql")):
                conn.execute(path.read_text())
            conn.commit()
        cls.connect = staticmethod(lambda url=cls.url: connect(url))
        cls.temp = tempfile.TemporaryDirectory()
        cls.auth = AuthTestContext(connect=cls.connect, username="pl5-trial")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{cls.dbname}" WITH (FORCE)')

    def test_message_media_retry_catchup_and_schedule_isolation(self):
        from sto.scheduling.working_schedule import Workspace
        from sto.persistence import repositories as repo

        with self.auth.client(Workspace(connect=self.connect,
                                        source_dir=Path(self.temp.name))) as client:
            project = client.post("/api/projects", json={"name": "PL5 trial"}).json()["id"]
            imported = client.post(f"/api/projects/{project}/imports",
                files={"file": (SOURCE.name, SOURCE.read_bytes(), "application/xml")})
            self.assertEqual(imported.status_code, 201, imported.text)
            self.assertEqual(client.post(f"/api/projects/{project}/calculations").status_code, 201)
            uid = client.get(f"/api/projects/{project}/planner").json()["eligible_activities"][0]["activity_uid"]
            before = client.get(f"/api/projects/{project}/live").json()
            message_id, media_id = str(uuid.uuid4()), str(uuid.uuid4())
            payload = {"id": message_id, "activity_uid": uid,
                       "text": "A-101 finished (communication only)"}
            endpoint = f"/api/projects/{project}/trial-messages"
            first = client.post(endpoint, json=payload)
            self.assertEqual(first.status_code, 201, first.text)
            self.assertEqual(first.json()["server_sequence"], 1)
            self.assertEqual(client.post(endpoint, json=payload).json(), first.json())
            conflict = client.post(endpoint, json={**payload, "text": "different"})
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["detail"]["code"], "TRIAL_ID_CONFLICT")
            media = {"id": media_id, "activity_uid": uid, "mime": "image/png",
                     "base64": "AAECAw==", "sha256":
                     hashlib.sha256(bytes([0, 1, 2, 3])).hexdigest(),
                     "annotations": [{"kind": "circle", "x": 0.5, "y": 0.5, "radius": 0.2}]}
            upload = client.post(f"/api/projects/{project}/trial-media", json=media)
            self.assertEqual(upload.status_code, 201, upload.text)
            self.assertEqual(client.post(f"/api/projects/{project}/trial-media",
                                         json=media).json(), upload.json())
            original = client.get(f"/api/projects/{project}/trial-media/{media_id}/original")
            self.assertEqual(original.content, bytes([0, 1, 2, 3]))
            self.assertEqual(original.headers["content-type"], "image/png")
            self.assertEqual(original.headers["x-content-type-options"], "nosniff")
            self.assertTrue(original.headers["content-disposition"].startswith("attachment;"))
            self.assertEqual(client.post(f"/api/projects/{project}/trial-media", json={
                **media, "base64": "AAECAQ==",
                "sha256": hashlib.sha256(bytes([0, 1, 2, 1])).hexdigest(),
            }).json()["detail"]["code"], "TRIAL_MEDIA_ID_CONFLICT")
            link_url = f"/api/projects/{project}/trial-media/{media_id}/link"
            link = client.post(link_url, json={"message_id": message_id})
            self.assertEqual(link.status_code, 201, link.text)
            self.assertEqual(client.post(link_url, json={"message_id": message_id}).json(),
                             link.json())
            page = client.get(f"/api/projects/{project}/changes", params={"after": 0}).json()
            self.assertEqual([e["kind"] for e in page["events"]],
                             ["trial_message", "trial_media_link"])
            self.assertEqual(page["events"][0]["activity_uid"], uid)
            self.assertEqual(page["next_cursor"], 2)
            after = client.get(f"/api/projects/{project}/live").json()
            self.assertEqual(after, before)
            with self.connect() as conn:
                self.assertEqual(repo.live_cursor(conn, uuid.UUID(project)), 2)
                self.assertEqual(conn.execute("SELECT count(*) AS n FROM live_execution_operations "
                                              "WHERE project_id=%s", (uuid.UUID(project),)).fetchone()["n"], 0)

    def test_authenticated_trial_build_identity_fails_closed_without_deployment_sha(self):
        from sto.scheduling.working_schedule import Workspace
        from sto.api.app import create_app
        from fastapi.testclient import TestClient

        workspace = Workspace(connect=self.connect, source_dir=Path(self.temp.name))
        with patch.dict(os.environ, {"STO_BUILD_SHA": "d" * 40}):
            with self.auth.client(workspace) as client:
                response = client.get("/api/trial-build")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), {"server_sha": "d" * 40})
        with patch.dict(os.environ, {"STO_BUILD_SHA": ""}):
            with self.auth.client(workspace) as client:
                self.assertEqual(client.get("/api/trial-build").status_code, 503)
            with TestClient(create_app(workspace, self.auth.service)) as guest:
                self.assertEqual(guest.get("/api/trial-build").status_code, 401)

    def test_media_before_message_and_current_authority(self):
        from sto.scheduling.working_schedule import Workspace
        from tests.auth_fixture import AuthTestContext
        from fastapi.testclient import TestClient
        from sto.api.app import create_app

        workspace = Workspace(connect=self.connect, source_dir=Path(self.temp.name))
        with self.auth.client(workspace) as owner:
            project = owner.post("/api/projects", json={"name": "PL5 authority"}).json()["id"]
            self.assertEqual(owner.post(f"/api/projects/{project}/imports", files={
                "file": (SOURCE.name, SOURCE.read_bytes(), "application/xml")}).status_code, 201)
            self.assertEqual(owner.post(f"/api/projects/{project}/calculations").status_code, 201)
            uids = [row["activity_uid"] for row in owner.get(f"/api/projects/{project}/planner").json()["eligible_activities"]]
            target = f"/api/projects/{project}/trial-messages"
            message_id, media_id = str(uuid.uuid4()), str(uuid.uuid4())
            media = {"id": media_id, "activity_uid": uids[0], "mime": "image/png",
                "base64": "AAECAw==", "sha256": hashlib.sha256(bytes([0, 1, 2, 3])).hexdigest(),
                "annotations": [{"kind": "arrow", "x": 0.1, "y": 0.2, "toX": 0.8, "toY": 0.9}]}
            self.assertEqual(owner.post(f"/api/projects/{project}/trial-media", json=media).status_code, 201)
            # Bytes accepted is not a message or schedule event.
            self.assertEqual(owner.get(f"/api/projects/{project}/changes").json()["events"], [])
            missing = owner.post(f"/api/projects/{project}/trial-media/{media_id}/link",
                                 json={"message_id": message_id})
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(owner.post(target, json={"id": message_id,
                "activity_uid": uids[1], "text": "wrong activity"}).status_code, 201)
            mismatch = owner.post(f"/api/projects/{project}/trial-media/{media_id}/link",
                                  json={"message_id": message_id})
            self.assertEqual(mismatch.status_code, 403)
            viewer = AuthTestContext(connect=self.connect, username=f"pl5-viewer-{uuid.uuid4().hex[:6]}")
            outsider = TestClient(create_app(workspace, viewer.service))
            self.assertEqual(outsider.get(f"/api/projects/{project}/trial-media/{media_id}/original").status_code, 401)
            with viewer.client(workspace) as other:
                self.assertEqual(other.get(f"/api/projects/{project}/trial-media/{media_id}/original").status_code, 404)
                grant = owner.post(f"/api/projects/{project}/memberships", json={
                    "user_id": str(viewer.user["id"]), "role": "viewer"})
                self.assertEqual(grant.status_code, 200)
                self.assertEqual(other.get(f"/api/projects/{project}/trial-media/{media_id}/original").content,
                                 bytes([0, 1, 2, 3]))
                self.assertEqual(other.post(target, json={"id": str(uuid.uuid4()),
                    "activity_uid": uids[0], "text": "viewer"}).status_code, 403)
                revoke = owner.delete(f"/api/projects/{project}/memberships/{viewer.user['id']}")
                self.assertEqual(revoke.status_code, 204)
                self.assertEqual(other.get(f"/api/projects/{project}/trial-media/{media_id}/original").status_code, 404)

    def test_trial_events_interleave_with_execution_and_replay_remains_exact(self):
        from sto.scheduling.working_schedule import Workspace
        from sto.scheduling.live_operations import replay

        with self.auth.client(Workspace(connect=self.connect,
                                        source_dir=Path(self.temp.name))) as client:
            project = client.post("/api/projects", json={"name": "PL5 replay"}).json()["id"]
            baseline = client.post(f"/api/projects/{project}/imports", files={
                "file": (SOURCE.name, SOURCE.read_bytes(), "application/xml")}).json()
            self.assertEqual(client.post(f"/api/projects/{project}/calculations").status_code, 201)
            uid = client.get(f"/api/projects/{project}/planner").json()["eligible_activities"][0]["activity_uid"]
            message = client.post(f"/api/projects/{project}/trial-messages", json={
                "id": str(uuid.uuid4()), "activity_uid": uid, "text": "Task complete"})
            self.assertEqual(message.status_code, 201, message.text)
            execution = client.post(f"/api/projects/{project}/execution-operations", json={
                "operation_id": str(uuid.uuid4()), "expected_version_id": baseline["version_id"],
                "expected_hash": baseline["canonical_hash"], "activity_uid": uid,
                "actual_start": "2026-01-05T09:00:00", "remaining_seconds": 3600})
            self.assertEqual(execution.status_code, 201, execution.text)
            self.assertEqual(execution.json()["server_sequence"], 2)
            live_calc = client.get(f"/api/projects/{project}/calculations/latest",
                                   params={"kind": "live_working"})
            self.assertEqual(live_calc.status_code, 200, live_calc.text)
            self.assertEqual(live_calc.json()["version_id"], execution.json()["result_version_id"])
            self.assertEqual(live_calc.json()["canonical_hash"], execution.json()["canonical_hash"])
            self.assertEqual(client.get(f"/api/projects/{project}/calculations/latest").json()[
                "version_id"], baseline["version_id"])
            proof = replay(client.app.state.workspace, uuid.UUID(project))
            self.assertEqual(proof["replay_hash"], execution.json()["canonical_hash"])
            self.assertEqual(client.get(f"/api/projects/{project}/changes").json()["events"][0]["kind"],
                             "trial_message")

    def test_device_bearer_cors_revocation_and_receipt_after_restart(self):
        from fastapi.testclient import TestClient
        from sto.api.app import create_app
        from sto.scheduling.working_schedule import Workspace

        workspace = Workspace(connect=self.connect, source_dir=Path(self.temp.name))
        with self.auth.client(workspace) as owner:
            project = owner.post("/api/projects", json={"name": "PL5 device auth"}).json()["id"]
            self.assertEqual(owner.post(f"/api/projects/{project}/imports", files={
                "file": (SOURCE.name, SOURCE.read_bytes(), "application/xml")}).status_code, 201)
            self.assertEqual(owner.post(f"/api/projects/{project}/calculations").status_code, 201)
            uid = owner.get(f"/api/projects/{project}/planner").json()["eligible_activities"][0]["activity_uid"]
            issued = owner.post(f"/api/projects/{project}/device-tokens", json={
                "user_id": str(self.auth.user["id"]), "role": "planner"})
            self.assertEqual(issued.status_code, 201, issued.text)
            raw = issued.json()["raw_token"]
            endpoint = f"/api/projects/{project}/trial-messages"
            payload = {"id": str(uuid.uuid4()), "activity_uid": uid, "text": "offline note"}
            with TestClient(create_app(workspace, self.auth.service)) as device:
                self.assertEqual(device.post(endpoint, json=payload).status_code, 401)
                preflight = device.options(endpoint, headers={
                    "Origin": "capacitor://localhost", "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type"})
                self.assertEqual(preflight.status_code, 200, preflight.text)
                device.headers["Authorization"] = f"Bearer {raw}"
                self.assertEqual(device.get("/api/auth/session").json()["actor"]["user_id"],
                                 str(self.auth.user["id"]))
                created = device.post(endpoint, json=payload)
                self.assertEqual(created.status_code, 201, created.text)
            with TestClient(create_app(workspace, self.auth.service)) as restarted:
                restarted.headers["Authorization"] = f"Bearer {raw}"
                self.assertEqual(restarted.get(f"{endpoint}/{payload['id']}").json(), created.json())
                self.assertEqual(restarted.post(endpoint, json=payload).status_code, 200)
                revoked = owner.delete(f"/api/projects/{project}/device-tokens/{issued.json()['id']}")
                self.assertEqual(revoked.status_code, 204, revoked.text)
                self.assertEqual(restarted.post(endpoint, json={**payload,
                    "id": str(uuid.uuid4())}).status_code, 401)
