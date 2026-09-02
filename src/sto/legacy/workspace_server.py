from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any
from urllib.parse import unquote_to_bytes, urlsplit
import webbrowser

from .mspdi import MspdiImportError, import_mspdi


MAX_IMPORT_BYTES = 64 * 1024 * 1024
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
DEFAULT_STATIC_DIR = Path(__file__).with_name("workspace_static")

Importer = Callable[[str | Path], dict[str, Any]]
SessionFactory = Callable[[dict[str, Any], str], Any]


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


class WorkspaceApplication:
    """Thread-safe holder for the single local workspace session."""

    def __init__(self, importer: Importer, session_factory: SessionFactory) -> None:
        self._importer = importer
        self._session_factory = session_factory
        self._lock = RLock()
        self._session: Any | None = None
        self._workspace_id: str | None = None
        self._source_filename: str | None = None

    @property
    def has_workspace(self) -> bool:
        with self._lock:
            return self._session is not None

    def import_source(self, source_path: Path, source_filename: str) -> dict[str, Any]:
        # Build the replacement before taking the lock so a failed import leaves
        # the current usable workspace intact.
        document = self._importer(source_path)
        session = self._session_factory(document, source_filename)
        workspace_id = self._workspace_id_for(session, document)
        view = self._view_from(session, None)
        with self._lock:
            self._session = session
            self._workspace_id = workspace_id
            self._source_filename = source_filename
        return self._with_transport_metadata(
            view, workspace_id, source_filename
        )

    def view(self, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(workspace_id)
            return self._with_transport_metadata(
                session.view(), workspace_id, self._required_source_filename()
            )

    def set_duration(
        self, workspace_id: str, activity_id: str, duration_seconds: int
    ) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(workspace_id)
            result = session.set_duration(activity_id, duration_seconds)
            return self._with_transport_metadata(
                self._view_from(session, result),
                workspace_id,
                self._required_source_filename(),
            )

    def reset(self, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(workspace_id)
            result = session.reset()
            return self._with_transport_metadata(
                self._view_from(session, result),
                workspace_id,
                self._required_source_filename(),
            )

    def export_state(self, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(workspace_id)
            state = session.export_state()
            if not isinstance(state, dict):
                raise RuntimeError("WorkspaceSession export_state() must return an object")
            return self._with_transport_metadata(
                state, workspace_id, self._required_source_filename()
            )

    def _require_session(self, workspace_id: str) -> Any:
        if (
            self._session is None
            or self._workspace_id is None
            or workspace_id != self._workspace_id
        ):
            raise RequestError(
                HTTPStatus.NOT_FOUND,
                "WORKSPACE_NOT_FOUND",
                "Workspace not found",
            )
        return self._session

    def _required_source_filename(self) -> str:
        if self._source_filename is None:
            raise RuntimeError("Workspace source filename is missing")
        return self._source_filename

    @staticmethod
    def _view_from(session: Any, result: object) -> dict[str, Any]:
        view = result if isinstance(result, dict) else session.view()
        if not isinstance(view, dict):
            raise RuntimeError("WorkspaceSession view() must return an object")
        return view

    @staticmethod
    def _workspace_id_for(
        session: Any, document: dict[str, Any]
    ) -> str:
        session_workspace_id = getattr(session, "workspace_id", None)
        if isinstance(session_workspace_id, str) and session_workspace_id:
            return session_workspace_id
        source = document.get("source")
        source_hash = source.get("sha256") if isinstance(source, dict) else None
        if not isinstance(source_hash, str) or not source_hash:
            raise RuntimeError("Imported document has no source SHA-256")
        return f"workspace:{source_hash}"

    @staticmethod
    def _with_transport_metadata(
        view: dict[str, Any], workspace_id: str, source_filename: str
    ) -> dict[str, Any]:
        source = view.get("source")
        if (
            view.get("workspace_id") == workspace_id
            and isinstance(source, dict)
            and source.get("file_name") == source_filename
        ):
            return view
        result = dict(view)
        result["workspace_id"] = workspace_id
        if isinstance(source, dict):
            result["source"] = dict(source)
            result["source"]["file_name"] = source_filename
        return result


class WorkspaceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        application: WorkspaceApplication,
        static_dir: Path,
    ) -> None:
        self.application = application
        self.static_dir = static_dir
        super().__init__(server_address, WorkspaceRequestHandler)


class WorkspaceRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    _STATIC_ROUTES = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    }

    @property
    def workspace_server(self) -> WorkspaceHTTPServer:
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch(self._handle_get)

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch(self._handle_post)

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch(self._handle_delete)

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch(lambda: self._handle_get(head_only=True))

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _dispatch(self, operation: Callable[[], None]) -> None:
        try:
            self._validate_local_request()
            operation()
        except RequestError as exc:
            self._send_json_error(exc.status, exc.code, exc.message)
        except MspdiImportError as exc:
            self._send_json_error(
                HTTPStatus.BAD_REQUEST, "IMPORT_FAILED", str(exc)
            )
        except ValueError as exc:
            code = getattr(exc, "code", "WORKSPACE_ERROR")
            status = (
                HTTPStatus.NOT_FOUND
                if code in {"TASK_NOT_FOUND", "ACTIVITY_NOT_FOUND"}
                else HTTPStatus.UNPROCESSABLE_ENTITY
            )
            metadata: dict[str, Any] = {}
            activity_id = getattr(exc, "activity_id", None)
            if activity_id is not None:
                metadata["activity_id"] = activity_id
            details = getattr(exc, "details", None)
            if isinstance(details, dict) and details:
                metadata["details"] = details
            self._send_json_error(
                status, str(code), str(exc), metadata=metadata
            )
        except Exception:
            # Local clients receive a stable error contract without implementation
            # details or a traceback. The handler deliberately suppresses logging.
            self._send_json_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "The local workspace request could not be completed",
            )

    def _validate_local_request(self) -> None:
        """Reject DNS rebinding and browser cross-origin mutations."""

        host_values = self.headers.get_all("Host", failobj=[])
        if len(host_values) != 1:
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_HOST",
                "A single local Host header is required",
            )
        if self._parse_local_authority(host_values[0]) is None:
            raise RequestError(
                HTTPStatus.FORBIDDEN,
                "NON_LOCAL_HOST",
                "The workspace accepts requests only through its local address",
            )

        if self.command not in {"POST", "DELETE"}:
            return
        origin_values = self.headers.get_all("Origin", failobj=[])
        if not origin_values:
            return
        if len(origin_values) != 1:
            raise RequestError(
                HTTPStatus.FORBIDDEN,
                "CROSS_ORIGIN_REQUEST",
                "Cross-origin workspace changes are not allowed",
            )
        try:
            origin = urlsplit(origin_values[0])
            origin_port = origin.port
        except ValueError:
            origin = None
            origin_port = None
        server_port = self.workspace_server.server_address[1]
        if (
            origin is None
            or origin.scheme != "http"
            or origin.username is not None
            or origin.password is not None
            or origin.hostname not in LOOPBACK_HOSTS
            or (origin_port if origin_port is not None else 80) != server_port
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            raise RequestError(
                HTTPStatus.FORBIDDEN,
                "CROSS_ORIGIN_REQUEST",
                "Cross-origin workspace changes are not allowed",
            )

    def _parse_local_authority(self, value: str) -> str | None:
        try:
            authority = urlsplit(f"//{value}")
            port = authority.port
        except ValueError:
            return None
        server_port = self.workspace_server.server_address[1]
        if (
            authority.username is not None
            or authority.password is not None
            or authority.hostname not in LOOPBACK_HOSTS
            or (port if port is not None else 80) != server_port
            or authority.path
            or authority.query
            or authority.fragment
        ):
            return None
        return authority.hostname

    def _handle_get(self, *, head_only: bool = False) -> None:
        path = urlsplit(self.path).path
        if path in self._STATIC_ROUTES:
            filename, content_type = self._STATIC_ROUTES[path]
            self._serve_static(filename, content_type, head_only=head_only)
            return
        if path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "workspace_loaded": self.workspace_server.application.has_workspace,
                },
                head_only=head_only,
            )
            return

        route = self._workspace_route(path)
        if route is None:
            raise RequestError(
                HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found"
            )
        workspace_id, action = route
        if action is None:
            value = self.workspace_server.application.view(workspace_id)
            self._send_json(HTTPStatus.OK, value, head_only=head_only)
            return
        if action == "export":
            value = self.workspace_server.application.export_state(workspace_id)
            payload = self._json_bytes(value, pretty=True)
            self._send_bytes(
                HTTPStatus.OK,
                payload,
                "application/json; charset=utf-8",
                extra_headers={
                    "Content-Disposition": 'attachment; filename="sto-workspace.json"'
                },
                head_only=head_only,
            )
            return
        raise RequestError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found")

    def _handle_post(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/import":
            self._handle_import()
            return

        route = self._workspace_route(path)
        if route is None or route[1] != "scenario":
            raise RequestError(
                HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found"
            )
        workspace_id, _ = route
        body = self._read_json_body(MAX_IMPORT_BYTES)
        activity_id = body.get("activity_id")
        duration_seconds = body.get("duration_seconds")
        if not isinstance(activity_id, str) or not activity_id:
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                "activity_id must be a non-empty string",
            )
        if type(duration_seconds) is not int:
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                "duration_seconds must be an integer",
            )
        value = self.workspace_server.application.set_duration(
            workspace_id, activity_id, duration_seconds
        )
        self._send_json(HTTPStatus.OK, value)

    def _handle_delete(self) -> None:
        route = self._workspace_route(urlsplit(self.path).path)
        if route is None or route[1] != "scenario":
            raise RequestError(
                HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found"
            )
        workspace_id, _ = route
        value = self.workspace_server.application.reset(workspace_id)
        self._send_json(HTTPStatus.OK, value)

    def _handle_import(self) -> None:
        payload = self._read_body(MAX_IMPORT_BYTES)
        if not payload:
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "EMPTY_IMPORT",
                "The MSPDI import body is empty",
            )
        source_filename = self._source_filename()
        with tempfile.TemporaryDirectory(prefix="sto-workspace-import-") as directory:
            source_path = Path(directory) / source_filename
            source_path.write_bytes(payload)
            value = self.workspace_server.application.import_source(
                source_path, source_filename
            )
        self._send_json(HTTPStatus.CREATED, value)

    def _serve_static(
        self,
        filename: str,
        content_type: str,
        *,
        head_only: bool,
    ) -> None:
        path = self.workspace_server.static_dir / filename
        try:
            payload = path.read_bytes()
        except OSError:
            raise RequestError(
                HTTPStatus.NOT_FOUND,
                "STATIC_ASSET_NOT_FOUND",
                "Static asset not found",
            ) from None
        self._send_bytes(
            HTTPStatus.OK,
            payload,
            content_type,
            extra_headers={"Cache-Control": "no-cache"},
            head_only=head_only,
        )

    def _read_json_body(self, maximum: int) -> dict[str, Any]:
        payload = self._read_body(maximum)
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_JSON",
                "Request body must be a UTF-8 JSON object",
            ) from None
        if not isinstance(value, dict):
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_JSON",
                "Request body must be a UTF-8 JSON object",
            )
        return value

    def _read_body(self, maximum: int) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise RequestError(
                HTTPStatus.LENGTH_REQUIRED,
                "CONTENT_LENGTH_REQUIRED",
                "Content-Length is required",
            )
        try:
            length = int(raw_length)
        except ValueError:
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_CONTENT_LENGTH",
                "Content-Length must be a non-negative integer",
            ) from None
        if length < 0:
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_CONTENT_LENGTH",
                "Content-Length must be a non-negative integer",
            )
        if length > maximum:
            raise RequestError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "IMPORT_TOO_LARGE",
                f"Request body exceeds the {MAX_IMPORT_BYTES // (1024 * 1024)} MiB limit",
            )
        payload = self.rfile.read(length)
        if len(payload) != length:
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INCOMPLETE_REQUEST_BODY",
                "Request body ended before Content-Length bytes were received",
            )
        return payload

    def _source_filename(self) -> str:
        encoded = self.headers.get("X-File-Name", "schedule.xml")
        try:
            decoded = unquote_to_bytes(encoded).decode("utf-8")
        except UnicodeDecodeError:
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_FILE_NAME",
                "X-File-Name must contain URI-encoded UTF-8",
            ) from None
        decoded = decoded.replace("\\", "/")
        filename = decoded.rsplit("/", 1)[-1]
        if (
            not filename
            or filename in {".", ".."}
            or any(ord(character) < 32 for character in filename)
        ):
            raise RequestError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_FILE_NAME",
                "X-File-Name must identify a file",
            )
        return filename

    @staticmethod
    def _workspace_route(path: str) -> tuple[str, str | None] | None:
        parts = path.split("/")
        if len(parts) not in {4, 5} or parts[:3] != ["", "api", "workspaces"]:
            return None
        try:
            workspace_id = unquote_to_bytes(parts[3]).decode("utf-8")
        except UnicodeDecodeError:
            return None
        if not workspace_id:
            return None
        if len(parts) == 4:
            return workspace_id, None
        action = parts[4]
        if action not in {"scenario", "export"}:
            return None
        return workspace_id, action

    def _method_not_allowed(self) -> None:
        self._send_json_error(
            HTTPStatus.METHOD_NOT_ALLOWED,
            "METHOD_NOT_ALLOWED",
            "Method not allowed",
        )

    def _send_json_error(
        self,
        status: int,
        code: str,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if metadata:
            error.update(metadata)
        # Some rejections happen before a request body is consumed (for
        # example, an oversized upload or an unsupported route). Closing that
        # connection prevents unread bytes from being parsed as another request.
        self.close_connection = True
        self._send_json(
            status,
            {"error": error},
        )

    def _send_json(
        self,
        status: int,
        value: object,
        *,
        head_only: bool = False,
    ) -> None:
        self._send_bytes(
            status,
            self._json_bytes(value),
            "application/json; charset=utf-8",
            head_only=head_only,
        )

    @staticmethod
    def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
        if pretty:
            text = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            ) + "\n"
        else:
            text = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        return text.encode("utf-8")

    def _send_bytes(
        self,
        status: int,
        payload: bytes,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
        head_only: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        del explain
        try:
            error_code = HTTPStatus(code).name
        except ValueError:
            error_code = "HTTP_ERROR"
        self._send_json_error(
            code,
            error_code,
            message or "HTTP request failed",
        )

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def _default_session_factory(
    document: dict[str, Any], source_filename: str
) -> Any:
    from .workspace import WorkspaceSession

    return WorkspaceSession.from_document(document, source_filename)


def create_workspace_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    static_dir: str | Path | None = None,
    importer: Importer = import_mspdi,
    session_factory: SessionFactory = _default_session_factory,
) -> WorkspaceHTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(
            "The Prototype 0 workspace can bind only to 127.0.0.1 or localhost"
        )
    application = WorkspaceApplication(importer, session_factory)
    return WorkspaceHTTPServer(
        (host, port),
        application,
        Path(static_dir) if static_dir is not None else DEFAULT_STATIC_DIR,
    )


def workspace_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sto-scheduler-workspace",
        description="Run the local STO schedule workspace",
    )
    parser.add_argument("--host", choices=LOOPBACK_HOSTS, default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)

    server = create_workspace_server(args.host, args.port)
    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}/"
    print(url, flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(workspace_main())
