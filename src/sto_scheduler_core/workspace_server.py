from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
import webbrowser

from .calculation_common import CalculationProfileError
from .mspdi_shared import MspdiImportError
from .workspace import ScheduleWorkspace, WorkspaceError


MAX_IMPORT_BYTES = 32 * 1024 * 1024
WEB_ROOT = Path(__file__).with_name("workspace_web")


class WorkspaceHTTPServer(HTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        workspace: ScheduleWorkspace | None = None,
    ) -> None:
        super().__init__(server_address, WorkspaceRequestHandler)
        self.workspace = workspace or ScheduleWorkspace()


class WorkspaceRequestHandler(BaseHTTPRequestHandler):
    server: WorkspaceHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        print(f"workspace: {self.address_string()} - {format % args}")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )

    def _send_bytes(
        self,
        status: HTTPStatus,
        payload: bytes,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self._security_headers()
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _send_json(
        self,
        status: HTTPStatus,
        value: object,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        payload = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        self._send_bytes(
            status,
            payload,
            "application/json; charset=utf-8",
            extra_headers=extra_headers,
        )

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": message, "status": status.value})

    def _path(self) -> str:
        return urlsplit(self.path).path

    def _host_is_local(self) -> bool:
        host = self.headers.get("Host", "").lower()
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _origin_is_local(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        origin = origin.lower()
        port = self.server.server_address[1]
        return origin in {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }

    def _read_body(self, *, maximum: int) -> bytes:
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            raise WorkspaceError("Content-Length is required")
        try:
            length = int(length_text)
        except ValueError as exc:
            raise WorkspaceError("Content-Length is invalid") from exc
        if length < 0:
            raise WorkspaceError("Content-Length is invalid")
        if length > maximum:
            raise OverflowError
        return self.rfile.read(length)

    def _read_json(self) -> dict[str, Any]:
        payload = self._read_body(maximum=64 * 1024)
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise WorkspaceError("Request body must be a JSON object")
        return value

    def _serve_static(self, path: str) -> bool:
        routes = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        }
        route = routes.get(path)
        if route is None:
            return False
        filename, content_type = route
        try:
            payload = (WEB_ROOT / filename).read_bytes()
        except OSError:
            self._send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Workspace web assets are unavailable",
            )
            return True
        self._send_bytes(HTTPStatus.OK, payload, content_type)
        return True

    def do_HEAD(self) -> None:
        if not self._host_is_local():
            self._send_error_json(HTTPStatus.FORBIDDEN, "Local host required")
            return
        if not self._serve_static(self._path()):
            self._send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_GET(self) -> None:
        if not self._host_is_local():
            self._send_error_json(HTTPStatus.FORBIDDEN, "Local host required")
            return
        path = self._path()
        if path == "/api/workspace":
            self._send_json(HTTPStatus.OK, self.server.workspace.snapshot())
            return
        if not self._serve_static(path):
            self._send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        if not self._host_is_local() or not self._origin_is_local():
            self._send_error_json(HTTPStatus.FORBIDDEN, "Local origin required")
            return
        path = self._path()
        try:
            if path == "/api/import":
                payload = self._read_body(maximum=MAX_IMPORT_BYTES)
                display_name = unquote(
                    self.headers.get("X-File-Name", "schedule.xml")
                )
                snapshot = self.server.workspace.load_mspdi_bytes(
                    payload, display_name=display_name
                )
            elif path == "/api/scenario/recalculate":
                body = self._read_json()
                activity_id = body.get("activity_id")
                if not isinstance(activity_id, str) or not activity_id:
                    raise WorkspaceError("activity_id is required")
                document_key = body.get("document_key")
                if not isinstance(document_key, str) or not document_key:
                    raise WorkspaceError("document_key is required")
                revision = body.get("revision")
                if type(revision) is not int or revision < 0:
                    raise WorkspaceError("revision must be a non-negative integer")
                snapshot = self.server.workspace.recalculate_duration(
                    activity_id,
                    body.get("duration_seconds"),
                    document_key=document_key,
                    revision=revision,
                )
            elif path == "/api/scenario/reset":
                body = self._read_json()
                document_key = body.get("document_key")
                if not isinstance(document_key, str) or not document_key:
                    raise WorkspaceError("document_key is required")
                revision = body.get("revision")
                if type(revision) is not int or revision < 0:
                    raise WorkspaceError("revision must be a non-negative integer")
                snapshot = self.server.workspace.reset(
                    document_key=document_key,
                    revision=revision,
                )
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Not found")
                return
        except OverflowError:
            self._send_error_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "Import exceeds the "
                f"{MAX_IMPORT_BYTES // (1024 * 1024)} MiB local limit",
            )
            return
        except (WorkspaceError, MspdiImportError, CalculationProfileError) as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._send_json(HTTPStatus.OK, snapshot)


def create_workspace_server(
    *, port: int = 8765, workspace: ScheduleWorkspace | None = None
) -> WorkspaceHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    return WorkspaceHTTPServer(("127.0.0.1", port), workspace)


def run_workspace_server(
    *,
    port: int = 8765,
    source: Path | None = None,
    open_browser: bool = True,
) -> None:
    workspace = ScheduleWorkspace()
    if source is not None:
        workspace.load_mspdi(source)
    server = create_workspace_server(port=port, workspace=workspace)
    address, bound_port = server.server_address
    url = f"http://{address}:{bound_port}/"
    print(f"Prototype 0 local schedule workspace: {url}")
    print("The server is bound to this computer only. Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWorkspace stopped.")
    finally:
        server.server_close()
