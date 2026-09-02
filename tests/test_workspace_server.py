from __future__ import annotations

from http.client import HTTPConnection
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import threading
import unittest

from sto_scheduler_core.workspace_server import create_workspace_server


CHAIN = Path(__file__).parent / "fixtures" / "prototype0-chain.mspdi.xml"
WEB_ROOT = (
    Path(__file__).parents[1] / "src" / "sto_scheduler_core" / "workspace_web"
)


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        if (
            tag == "link"
            and values.get("rel") == "stylesheet"
            and values.get("href")
        ):
            self.stylesheets.append(values["href"])


class WorkspaceServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_workspace_server(port=0)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.connection = HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=5
        )

    def tearDown(self) -> None:
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(
        self,
        method: str,
        path: str,
        body: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        self.connection.request(method, path, body=body, headers=headers or {})
        response = self.connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload

    def test_static_workspace_is_served_with_local_security_headers(self) -> None:
        status, headers, payload = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Local schedule workspace", payload)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

        status, _, payload = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"downstream_moved_activity_count", payload)

    def test_web_asset_selectors_and_routes_are_self_contained(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        parser = _AssetParser()
        parser.feed(html)

        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        selected_ids = set(re.findall(r'querySelector\("#([A-Za-z0-9_-]+)"\)', script))
        self.assertLessEqual(selected_ids, set(parser.ids))
        self.assertEqual(parser.scripts, ["/app.js"])
        self.assertEqual(parser.stylesheets, ["/styles.css"])
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("<script>", html)
        self.assertIn("new Blob", script)
        self.assertIn("prototype-0-local-schedule-workspace-state", script)

    def test_http_vertical_slice_imports_recalculates_and_resets(self) -> None:
        status, _, payload = self.request("GET", "/api/workspace")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(payload)["loaded"])

        source = CHAIN.read_bytes()
        status, _, payload = self.request(
            "POST",
            "/api/import",
            source,
            {
                "Content-Type": "application/xml",
                "X-File-Name": "prototype0-chain.xml",
            },
        )
        self.assertEqual(status, 200)
        imported = json.loads(payload)
        self.assertEqual(imported["counts"]["tasks"], 5)
        self.assertEqual(imported["counts"]["supported_activities"], 3)

        request = json.dumps(
            {
                "document_key": imported["source"]["document_key"],
                "revision": imported["scenario"]["revision"],
                "activity_id": "task:2",
                "duration_seconds": 28800,
            }
        )
        status, _, payload = self.request(
            "POST",
            "/api/scenario/recalculate",
            request,
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        scenario = json.loads(payload)
        self.assertEqual(scenario["scenario"]["moved_activity_count"], 3)

        status, _, payload = self.request(
            "POST",
            "/api/scenario/reset",
            json.dumps(
                {
                    "document_key": scenario["source"]["document_key"],
                    "revision": scenario["scenario"]["revision"],
                }
            ),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        reset = json.loads(payload)
        self.assertFalse(reset["scenario"]["changed"])
        self.assertTrue(reset["loaded"])

    def test_api_rejects_stale_document_identity(self) -> None:
        status, _, payload = self.request(
            "POST",
            "/api/import",
            CHAIN.read_bytes(),
            {"Content-Type": "application/xml"},
        )
        self.assertEqual(status, 200)
        imported = json.loads(payload)
        status, _, payload = self.request(
            "POST",
            "/api/scenario/recalculate",
            json.dumps(
                {
                    "document_key": "sha256:stale",
                    "revision": 0,
                    "activity_id": "task:2",
                    "duration_seconds": 28800,
                }
            ),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("different imported schedule", json.loads(payload)["error"])

        status, _, payload = self.request(
            "POST",
            "/api/scenario/recalculate",
            json.dumps(
                {
                    "document_key": imported["source"]["document_key"],
                    "revision": imported["scenario"]["revision"],
                    "activity_id": "task:2",
                    "duration_seconds": 28800,
                }
            ),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)

        status, _, payload = self.request(
            "POST",
            "/api/scenario/reset",
            json.dumps(
                {
                    "document_key": imported["source"]["document_key"],
                    "revision": imported["scenario"]["revision"],
                }
            ),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("another workspace tab", json.loads(payload)["error"])

        status, _, payload = self.request(
            "POST",
            "/api/scenario/reset",
            json.dumps(
                {
                    "document_key": "sha256:stale",
                    "revision": 0,
                }
            ),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("different imported schedule", json.loads(payload)["error"])

    def test_api_rejects_non_local_browser_origin(self) -> None:
        status, _, payload = self.request(
            "POST",
            "/api/import",
            CHAIN.read_bytes(),
            {
                "Content-Type": "application/xml",
                "Origin": "https://example.invalid",
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(payload)["error"], "Local origin required")

    def test_http_import_keeps_hierarchy_when_calculation_start_is_missing(
        self,
    ) -> None:
        source = CHAIN.read_bytes().replace(
            b"  <StartDate>2026-01-05T08:00:00</StartDate>\n",
            b"",
            1,
        )
        status, _, payload = self.request(
            "POST",
            "/api/import",
            source,
            {"Content-Type": "application/xml"},
        )
        self.assertEqual(status, 200)
        snapshot = json.loads(payload)
        self.assertEqual(snapshot["counts"]["tasks"], 5)
        self.assertFalse(snapshot["calculation"]["available"])
        self.assertEqual(snapshot["counts"]["supported_activities"], 0)


if __name__ == "__main__":
    unittest.main()
