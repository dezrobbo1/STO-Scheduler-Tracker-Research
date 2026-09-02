from __future__ import annotations

from http import HTTPStatus
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.parse import quote

from sto_scheduler_core.mspdi import MspdiImportError, import_mspdi
from sto_scheduler_core.workspace_server import (
    MAX_IMPORT_BYTES,
    create_workspace_server,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "synthetic-workspace-chain.mspdi.xml"
)


class FakeWorkspaceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FakeWorkspaceSession:
    def __init__(self, document: dict[str, object], source_filename: str) -> None:
        source = document["source"]
        assert isinstance(source, dict)
        source_hash = source["sha256"]
        self.workspace_id = f"workspace:{source_hash}"
        self.source_filename = source_filename
        self.revision = 0
        self.duration_seconds = 3600

    def view(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "revision": self.revision,
            "source": {"filename": self.source_filename},
            "tasks": [
                {
                    "id": "task:1",
                    "duration_seconds": self.duration_seconds,
                }
            ],
        }

    def set_duration(
        self, activity_id: str, duration_seconds: int
    ) -> dict[str, object]:
        if activity_id == "task:missing":
            raise FakeWorkspaceError("TASK_NOT_FOUND", "Task not found")
        if activity_id != "task:1":
            raise FakeWorkspaceError("TASK_NOT_EDITABLE", "Task is not editable")
        if duration_seconds <= 0:
            raise FakeWorkspaceError("INVALID_DURATION", "Duration must be positive")
        self.duration_seconds = duration_seconds
        self.revision += 1
        return self.view()

    def reset(self) -> dict[str, object]:
        if self.duration_seconds != 3600:
            self.duration_seconds = 3600
            self.revision += 1
        return self.view()

    def export_state(self) -> dict[str, object]:
        return {
            "workspace_schema_version": "0.1.0",
            "workspace_id": self.workspace_id,
            "revision": self.revision,
            "duration_overrides_seconds": (
                {} if self.duration_seconds == 3600 else {"task:1": self.duration_seconds}
            ),
        }


class WorkspaceServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.static_dir = Path(self.temporary_directory.name) / "static"
        self.static_dir.mkdir()
        (self.static_dir / "index.html").write_text(
            "<!doctype html><title>Workspace</title>", encoding="utf-8"
        )
        (self.static_dir / "app.js").write_text(
            "globalThis.workspaceLoaded = true;", encoding="utf-8"
        )
        (self.static_dir / "styles.css").write_text(
            "body { color: black; }", encoding="utf-8"
        )

        self.import_calls: list[Path] = []
        self.import_payloads: list[bytes] = []
        self.import_paths_existed: list[bool] = []
        self.sessions: list[FakeWorkspaceSession] = []

        def importer(path: str | Path) -> dict[str, object]:
            source_path = Path(path)
            self.import_calls.append(source_path)
            self.import_paths_existed.append(source_path.is_file())
            self.import_payloads.append(source_path.read_bytes())
            return {"source": {"sha256": "a" * 64}}

        def session_factory(
            document: dict[str, object], source_filename: str
        ) -> FakeWorkspaceSession:
            session = FakeWorkspaceSession(document, source_filename)
            self.sessions.append(session)
            return session

        self.server = create_workspace_server(
            "127.0.0.1",
            0,
            static_dir=self.static_dir,
            importer=importer,
            session_factory=session_factory,
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.port = self.server.server_address[1]

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            return response.status, response_headers, response.read()
        finally:
            connection.close()

    def _import_workspace(self) -> dict[str, object]:
        status, _, payload = self._request(
            "POST",
            "/api/import",
            body=b"<Project />",
            headers={"X-File-Name": quote("Boiler shutdown.xml", safe="")},
        )
        self.assertEqual(status, HTTPStatus.CREATED)
        value = json.loads(payload)
        self.assertIsInstance(value, dict)
        return value

    def test_health_and_static_assets(self) -> None:
        status, headers, payload = self._request("GET", "/api/health")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(
            json.loads(payload), {"status": "ok", "workspace_loaded": False}
        )
        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")

        expected = {
            "/": ("text/html; charset=utf-8", b"<title>Workspace</title>"),
            "/app.js": ("text/javascript; charset=utf-8", b"workspaceLoaded"),
            "/styles.css": ("text/css; charset=utf-8", b"color: black"),
        }
        for path, (content_type, fragment) in expected.items():
            with self.subTest(path=path):
                status, headers, payload = self._request("GET", path)
                self.assertEqual(status, HTTPStatus.OK)
                self.assertEqual(headers["content-type"], content_type)
                self.assertIn(fragment, payload)

    def test_server_enforces_local_host_and_same_origin_mutations(self) -> None:
        with self.assertRaisesRegex(ValueError, "bind only"):
            create_workspace_server(
                "0.0.0.0",
                0,
                static_dir=self.static_dir,
                importer=lambda path: {"source": {"sha256": "b" * 64}},
                session_factory=lambda document, filename: FakeWorkspaceSession(
                    document, filename
                ),
            )

        status, _, payload = self._request(
            "GET", "/api/health", headers={"Host": "attacker.example"}
        )
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(json.loads(payload)["error"]["code"], "NON_LOCAL_HOST")

        status, _, payload = self._request(
            "POST",
            "/api/import",
            body=b"<Project />",
            headers={
                "Content-Type": "text/plain",
                "Origin": "https://attacker.example",
            },
        )
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "CROSS_ORIGIN_REQUEST"
        )
        self.assertEqual(self.import_calls, [])

        status, _, _ = self._request(
            "POST",
            "/api/import",
            body=b"<Project />",
            headers={"Origin": f"http://127.0.0.1:{self.port}"},
        )
        self.assertEqual(status, HTTPStatus.CREATED)

    def test_import_uses_one_temporary_file_and_returns_only_view(self) -> None:
        source = b"<Project xmlns='http://schemas.microsoft.com/project' />"
        status, _, payload = self._request(
            "POST",
            "/api/import",
            body=source,
            headers={
                "X-File-Name": quote("folder/Boiler shutdown.xml", safe="")
            },
        )

        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertEqual(len(self.import_calls), 1)
        self.assertEqual(self.import_payloads, [source])
        self.assertEqual(self.import_paths_existed, [True])
        self.assertFalse(self.import_calls[0].exists())
        self.assertEqual(self.sessions[0].source_filename, "Boiler shutdown.xml")
        view = json.loads(payload)
        self.assertEqual(view["workspace_id"], f"workspace:{'a' * 64}")
        self.assertNotIn("canonical", view)
        self.assertNotIn("vendor_extensions", view)

        status, _, health_payload = self._request("GET", "/api/health")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(json.loads(health_payload)["workspace_loaded"])

    def test_view_scenario_reset_and_downloadable_export(self) -> None:
        imported = self._import_workspace()
        workspace_id = imported["workspace_id"]
        self.assertIsInstance(workspace_id, str)
        encoded_id = quote(workspace_id, safe="")

        status, _, payload = self._request(
            "GET", f"/api/workspaces/{encoded_id}"
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(json.loads(payload)["revision"], 0)

        status, _, payload = self._request(
            "POST",
            f"/api/workspaces/{encoded_id}/scenario",
            body=json.dumps(
                {"activity_id": "task:1", "duration_seconds": 7200}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, HTTPStatus.OK)
        changed = json.loads(payload)
        self.assertEqual(changed["revision"], 1)
        self.assertEqual(changed["tasks"][0]["duration_seconds"], 7200)

        status, headers, payload = self._request(
            "GET", f"/api/workspaces/{encoded_id}/export"
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        self.assertEqual(
            headers["content-disposition"],
            'attachment; filename="sto-workspace.json"',
        )
        exported = json.loads(payload)
        self.assertEqual(
            exported["duration_overrides_seconds"], {"task:1": 7200}
        )
        self.assertNotIn("canonical", exported)

        status, _, payload = self._request(
            "DELETE", f"/api/workspaces/{encoded_id}/scenario"
        )
        self.assertEqual(status, HTTPStatus.OK)
        reset = json.loads(payload)
        self.assertEqual(reset["revision"], 2)
        self.assertEqual(reset["tasks"][0]["duration_seconds"], 3600)

    def test_workspace_and_route_errors_are_json_without_tracebacks(self) -> None:
        status, headers, payload = self._request(
            "GET", "/api/workspaces/workspace%3Amissing"
        )
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        error = json.loads(payload)["error"]
        self.assertEqual(error["code"], "WORKSPACE_NOT_FOUND")
        self.assertNotIn(b"Traceback", payload)

        status, _, payload = self._request("GET", "/does-not-exist")
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertEqual(json.loads(payload)["error"]["code"], "NOT_FOUND")

        status, _, payload = self._request("PUT", "/api/import", body=b"x")
        self.assertEqual(status, HTTPStatus.METHOD_NOT_ALLOWED)
        self.assertEqual(
            json.loads(payload)["error"]["code"], "METHOD_NOT_ALLOWED"
        )

    def test_scenario_request_validation_and_workspace_error_mapping(self) -> None:
        workspace_id = self._import_workspace()["workspace_id"]
        assert isinstance(workspace_id, str)
        path = f"/api/workspaces/{quote(workspace_id, safe='')}/scenario"

        status, _, payload = self._request(
            "POST", path, body=b"not-json", headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(json.loads(payload)["error"]["code"], "INVALID_JSON")

        status, _, payload = self._request(
            "POST",
            path,
            body=json.dumps(
                {"activity_id": "task:1", "duration_seconds": True}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(json.loads(payload)["error"]["code"], "INVALID_REQUEST")

        status, _, payload = self._request(
            "POST",
            path,
            body=json.dumps(
                {"activity_id": "task:missing", "duration_seconds": 7200}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertEqual(json.loads(payload)["error"]["code"], "TASK_NOT_FOUND")

        status, _, payload = self._request(
            "POST",
            path,
            body=json.dumps(
                {"activity_id": "task:summary", "duration_seconds": 7200}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertEqual(json.loads(payload)["error"]["code"], "TASK_NOT_EDITABLE")

    def test_import_size_limit_is_checked_before_body_read(self) -> None:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.putrequest("POST", "/api/import")
            connection.putheader("Content-Length", str(MAX_IMPORT_BYTES + 1))
            connection.endheaders()
            response = connection.getresponse()
            payload = response.read()
        finally:
            connection.close()

        self.assertEqual(response.status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(json.loads(payload)["error"]["code"], "IMPORT_TOO_LARGE")
        self.assertEqual(self.import_calls, [])

    def test_import_failures_are_safe_json_and_do_not_replace_workspace(self) -> None:
        imported = self._import_workspace()
        workspace_id = imported["workspace_id"]
        assert isinstance(workspace_id, str)

        def failed_importer(path: str | Path) -> dict[str, object]:
            del path
            raise MspdiImportError("synthetic import failure")

        self.server.application._importer = failed_importer
        status, _, payload = self._request(
            "POST", "/api/import", body=b"broken", headers={"X-File-Name": "broken.xml"}
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        error = json.loads(payload)["error"]
        self.assertEqual(error["code"], "IMPORT_FAILED")
        self.assertNotIn(b"Traceback", payload)

        status, _, payload = self._request(
            "GET", f"/api/workspaces/{quote(workspace_id, safe='')}"
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(json.loads(payload)["workspace_id"], workspace_id)

    def test_real_workspace_import_and_scenario_integrate_through_http(
        self,
    ) -> None:
        import_count = 0

        def counted_importer(path: str | Path) -> dict[str, object]:
            nonlocal import_count
            import_count += 1
            return import_mspdi(path)

        server = create_workspace_server(
            "127.0.0.1",
            0,
            static_dir=self.static_dir,
            importer=counted_importer,
        )
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop_integration_server() -> None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(stop_integration_server)
        port = server.server_address[1]
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(
                "POST",
                "/api/import",
                body=FIXTURE.read_bytes(),
                headers={"X-File-Name": quote(FIXTURE.name, safe="")},
            )
            response = connection.getresponse()
            payload = response.read()
        finally:
            connection.close()

        self.assertEqual(response.status, HTTPStatus.CREATED)
        self.assertEqual(import_count, 1)
        view = json.loads(payload)
        self.assertEqual(view["counts"]["tasks"], 6)
        self.assertEqual(view["counts"]["editable_activities"], 3)
        self.assertEqual(view["source"]["file_name"], FIXTURE.name)
        self.assertEqual(
            view["workspace_id"],
            f"workspace:{view['source']['sha256']}",
        )
        self.assertNotIn("vendor_extensions", view)

        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(
                "POST",
                (
                    f"/api/workspaces/{quote(view['workspace_id'], safe='')}"
                    "/scenario"
                ),
                body=json.dumps(
                    {"activity_id": "task:2", "duration_seconds": 8 * 60 * 60}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            scenario_response = connection.getresponse()
            scenario_payload = scenario_response.read()
        finally:
            connection.close()

        self.assertEqual(scenario_response.status, HTTPStatus.OK)
        changed = json.loads(scenario_payload)
        self.assertEqual(changed["revision"], 1)
        self.assertEqual(changed["scenario"]["moved_task_count"], 4)
        task = next(item for item in changed["tasks"] if item["id"] == "task:2")
        self.assertEqual(task["duration"]["current_seconds"], 8 * 60 * 60)
        self.assertEqual(
            task["calculated"]["current_finish"], "2026-01-05T17:00:00"
        )


if __name__ == "__main__":
    unittest.main()
