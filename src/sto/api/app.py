"""FastAPI application. One worker, one process, one resident workspace.

Boot rebuilds every project's baseline head from the database and verifies its
hash. That is the persistence gate in operational form: if a restart cannot
reproduce what it stored, the process does not come up quietly.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

#: The largest upload this API will read. A schedule of CALCINER's size is
#: fourteen megabytes; the legacy workspace already refused past sixty-four,
#: and reading an unbounded body into memory on the one worker that also does
#: the parsing is how a single request takes the process with it.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

#: A multipart body carries boundaries, headers and a filename around the file
#: itself, so the declared length of a request at the limit is a little over
#: it. The slack is for that envelope, not for the file.
_MULTIPART_ALLOWANCE = 8 * 1024

#: The read-only page, beside this module so that packaging carries it.
STATIC_DIR = Path(__file__).with_name("static")

from sto.core.model.migrate.sto_v011 import MigrationError
from sto.persistence import repositories as repo
from sto.persistence import auth_repositories as auth_repo
from sto.persistence.db import connect
from sto.core.calendar.compile import CalendarCompileError
from sto.core.engine.network import NetworkError
from sto.scheduling.working_schedule import (
    ImportRefused,
    IntegrityError,
    NoSchedule,
    ScenarioRejected,
    StaleSchedule,
    UnknownProject,
    Workspace,
)

from . import schemas
from .auth import (
    Actor,
    AuthService,
    AuthenticationFailed,
    AuthorizationFailed,
    ProjectAccess,
    lesser_role,
    role_allows,
)

#: 8090 is the Java API until cut-over (frozen-repository deployment); the new
#: stack is trialled beside it. The port swaps at PL12, not before.
DEFAULT_PORT = 8092


class BoundedBody:
    """Count the body as it arrives and refuse it when it passes the limit.

    A limit applied to the ``UploadFile`` is applied too late: multipart
    parsing consumes and spools the whole part before the endpoint is entered,
    so a client that omits or understates ``Content-Length`` has already
    written an arbitrary number of bytes to temporary disk by then. This sits
    below the parser, on the ASGI ``receive`` the parser reads from, which is
    the only place in this process where bytes can be refused *as they arrive*.

    The refusal is written here rather than raised. FastAPI turns any exception
    out of the body stream into "there was an error parsing the body", which
    would report a request that was deliberately cut off as a malformed one.
    So the stream is ended and whatever the application answers with is
    replaced by the 413 this middleware means.

    A proxy in front of the service should carry a limit too. This is the one
    that holds when nothing is in front of it.
    """

    def __init__(self, app, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)

        seen = 0
        tripped = False

        async def bounded():
            nonlocal seen, tripped
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    tripped = True
                    # Ending the stream, not raising: the parser sees a client
                    # that stopped sending, which is what happened.
                    return {"type": "http.disconnect"}
            return message

        answered = False

        async def guarded(message):
            nonlocal answered
            if not tripped:
                return await send(message)
            if message["type"] == "http.response.start":
                body = json.dumps(
                    {
                        "detail": f"the upload exceeds {self.limit} bytes; "
                        f"it was stopped at {seen}"
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body, "more_body": False})
                answered = True
                return
            if message["type"] == "http.response.body" and answered:
                return
            await send(message)

        return await self.app(scope, bounded, guarded)


def _refuse_oversized_body(request: Request) -> None:
    """Refuse an oversized upload before anything reads it.

    A declared length is not proof of anything, but it is what an honest
    client sends and what a proxy sets, and refusing on it costs the server
    nothing. A body that arrives without one, or that lies, is still bounded
    by the chunked read below -- this only moves the refusal earlier for the
    ordinary case, which is the case that fills a disk.
    """

    declared = request.headers.get("content-length")
    if declared is None:
        return
    try:
        length = int(declared)
    except ValueError:
        raise HTTPException(400, "the request declares a length that is not a number") from None
    if length > MAX_UPLOAD_BYTES + _MULTIPART_ALLOWANCE:
        raise HTTPException(
            413,
            f"the upload declares {length} bytes; the limit is {MAX_UPLOAD_BYTES}",
        )


async def _read_bounded(file: UploadFile) -> bytes:
    """The body, or a refusal before it is all in memory.

    Read in chunks and stopped at the bound rather than read whole and
    measured afterwards, which would mean holding the thing being refused.
    """

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"the upload is larger than {MAX_UPLOAD_BYTES} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def create_app(
    workspace: Workspace | None = None, auth_service: AuthService | None = None
) -> FastAPI:
    workspace = workspace or Workspace(connect=connect)
    auth_service = auth_service or AuthService.from_environment(connect=workspace.connect)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.resident = workspace.rebuild()
        yield

    # The controlled-trial surface is the login route, protected application
    # API, static login/planner shell and the deliberately content-free
    # liveness probe. FastAPI's interactive schema pages are useful during
    # development but are not part of that deployed boundary.
    app = FastAPI(
        title="STO",
        version="0.1",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.workspace = workspace
    app.state.auth = auth_service
    # Below the multipart parser, so an oversized body is refused while it is
    # arriving rather than after it has been spooled.
    app.add_middleware(BoundedBody, limit=MAX_UPLOAD_BYTES + _MULTIPART_ALLOWANCE)

    @app.middleware("http")
    async def keep_actor_responses_out_of_shared_caches(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            # These URLs are actor-specific even when their path is identical.
            # no-store is the boundary; Vary is defence in depth for a proxy
            # that mishandles or rewrites cache-control.
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "Cookie, Authorization"
        return response

    def ws(request: Request) -> Workspace:
        return request.app.state.workspace

    def auth(request: Request) -> AuthService:
        return request.app.state.auth

    def _unauthenticated() -> None:
        raise HTTPException(
            401,
            "authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _actor(request: Request) -> Actor:
        existing = getattr(request.state, "actor", None)
        if existing is not None:
            return existing
        service = auth(request)
        authorization = request.headers.get("authorization")
        raw_session: str | None = None
        try:
            if authorization is not None:
                scheme, separator, raw = authorization.partition(" ")
                if separator != " " or scheme.lower() != "bearer" or not raw:
                    _unauthenticated()
                actor = service.authenticate_device(raw)
            else:
                raw_session = request.cookies.get(service.config.cookie_name)
                if not raw_session:
                    _unauthenticated()
                actor = service.authenticate_session(raw_session)
        except AuthenticationFailed:
            _unauthenticated()
        request.state.actor = actor
        request.state.raw_session_token = raw_session
        return actor

    def _csrf(request: Request, actor: Actor) -> None:
        if actor.authentication == "device":
            return
        raw = getattr(request.state, "raw_session_token", None)
        if not auth(request).valid_csrf(raw, request.headers.get("x-csrf-token")):
            raise HTTPException(403, "CSRF validation failed")

    def authenticated(*, mutation: bool = False, browser_only: bool = False):
        def dependency(request: Request) -> Actor:
            actor = _actor(request)
            if browser_only and actor.authentication != "browser":
                raise HTTPException(403, "browser authentication required")
            if mutation:
                _csrf(request, actor)
            return actor

        dependency.__name__ = (
            "authenticated_browser_mutation"
            if browser_only and mutation
            else "authenticated_mutation"
            if mutation
            else "authenticated_request"
        )
        dependency._sto_policy = "authenticated"  # type: ignore[attr-defined]
        dependency._sto_mutation = mutation  # type: ignore[attr-defined]
        return dependency

    def project_role(required: str, *, mutation: bool = False):
        def dependency(request: Request, project_id: uuid.UUID) -> ProjectAccess:
            actor = _actor(request)
            if mutation:
                _csrf(request, actor)
            if actor.project_id is not None and actor.project_id != project_id:
                raise HTTPException(404, "no such project")
            with request.app.state.workspace.connect() as conn:
                membership = auth_repo.get_membership(
                    conn, project_id=project_id, user_id=actor.user_id
                )
            if membership is None:
                raise HTTPException(404, "no such project")
            effective_role = membership["role"]
            if actor.role_cap is not None:
                effective_role = lesser_role(effective_role, actor.role_cap)
            if not role_allows(effective_role, required):
                raise HTTPException(403, f"{required} project role required")
            return ProjectAccess(actor=actor, project_id=project_id, role=effective_role)

        dependency.__name__ = f"require_project_{required}"
        dependency._sto_policy = "project"  # type: ignore[attr-defined]
        dependency._sto_role = required  # type: ignore[attr-defined]
        dependency._sto_mutation = mutation  # type: ignore[attr-defined]
        return dependency

    require_viewer = project_role("viewer")
    require_planner = project_role("planner", mutation=True)
    require_admin = project_role("admin", mutation=True)
    require_admin_read = project_role("admin")

    @app.get("/healthz", include_in_schema=False)
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/auth/login", response_model=schemas.SessionResponse)
    def login(
        body: schemas.LoginRequest,
        request: Request,
        response: Response,
        service: AuthService = Depends(auth),
    ) -> Any:
        try:
            result = service.login(
                username=body.username,
                password=body.password,
                otp=body.totp,
                replace_raw_session=request.cookies.get(service.config.cookie_name),
            )
        except AuthenticationFailed:
            raise HTTPException(401, "authentication failed") from None
        response.set_cookie(
            key=service.config.cookie_name,
            value=result.raw_session_token,
            max_age=int(service.config.session_ttl.total_seconds()),
            expires=result.expires_at,
            secure=service.config.cookie_secure,
            httponly=True,
            samesite="strict",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return schemas.SessionResponse(
            actor=schemas.ActorResponse(**result.actor.public()),
            csrf_token=result.csrf_token,
            expires_at=result.expires_at,
        )

    @app.get("/api/auth/session", response_model=schemas.SessionResponse)
    def session(
        request: Request,
        response: Response,
        actor: Actor = Depends(authenticated()),
        service: AuthService = Depends(auth),
    ) -> Any:
        response.headers["Cache-Control"] = "no-store"
        raw = getattr(request.state, "raw_session_token", None)
        return schemas.SessionResponse(
            actor=schemas.ActorResponse(**actor.public()),
            csrf_token=None if raw is None else service.csrf_token(raw),
        )

    @app.post("/api/auth/logout", status_code=204)
    def logout(
        response: Response,
        actor: Actor = Depends(authenticated(mutation=True, browser_only=True)),
        service: AuthService = Depends(auth),
    ) -> Response:
        assert actor.session_id is not None
        service.revoke_session(actor.session_id)
        response.delete_cookie(
            service.config.cookie_name,
            path="/",
            secure=service.config.cookie_secure,
            httponly=True,
            samesite="strict",
        )
        response.status_code = 204
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health", response_model=schemas.Health)
    def health(
        actor: Actor = Depends(authenticated()), workspace: Workspace = Depends(ws)
    ) -> Any:
        try:
            with workspace.connect() as conn:
                conn.execute("SELECT 1")
                visible = repo.list_projects_for_user(
                    conn, user_id=actor.user_id, project_id=actor.project_id
                )
            database = "ok"
        except Exception as error:  # noqa: BLE001 - reported, not hidden
            database = f"error: {type(error).__name__}"
            visible = []
        visible_ids = {row["id"] for row in visible}
        failures = {
            project_id: failure
            for project_id, failure in workspace.integrity_failures.items()
            if project_id in visible_ids
        }
        return schemas.Health(
            status="ok" if database == "ok" and not failures else "degraded",
            database=database,
            resident_projects=len(workspace.resident_ids() & visible_ids),
            integrity_failures=failures,
        )

    @app.post("/api/projects", response_model=schemas.Project, status_code=201)
    def create_project(
        body: schemas.ProjectCreate,
        actor: Actor = Depends(authenticated(mutation=True, browser_only=True)),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        with workspace.connect() as conn:
            row = repo.create_project(
                conn,
                name=body.name,
                timezone=body.timezone,
                description=body.description,
                created_by_user_id=actor.user_id,
            )
            try:
                auth_repo.grant_membership(
                    conn,
                    project_id=row["id"],
                    user_id=actor.user_id,
                    role="admin",
                    created_by_user_id=actor.user_id,
                )
            except auth_repo.DisabledUser:
                raise HTTPException(401, "authentication required") from None
            conn.commit()
        return schemas.Project(**row)

    @app.get("/api/projects", response_model=list[schemas.Project])
    def list_projects(
        actor: Actor = Depends(authenticated()), workspace: Workspace = Depends(ws)
    ) -> Any:
        with workspace.connect() as conn:
            rows = repo.list_projects_for_user(
                conn, user_id=actor.user_id, project_id=actor.project_id
            )
            heads = {
                h["project_id"]: h
                for h in repo.heads_for_all_projects(conn)
                if h["head_kind"] == "baseline"
            }
        return [schemas.Project(**row, baseline=_head(heads.get(row["id"]))) for row in rows]

    @app.get("/api/projects/{project_id}", response_model=schemas.Project)
    def get_project(
        project_id: uuid.UUID,
        access: ProjectAccess = Depends(require_viewer),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        with workspace.connect() as conn:
            row = repo.get_project(conn, project_id)
            if row is None:
                raise HTTPException(404, "no such project")
            head = repo.head_version(
                conn, project_id=project_id, kind="baseline", with_document=False
            )
        return schemas.Project(**row, baseline=_head(head))

    @app.post(
        "/api/projects/{project_id}/imports",
        response_model=schemas.ImportResponse,
        status_code=201,
    )
    async def import_schedule(
        request: Request,
        project_id: uuid.UUID,
        file: UploadFile = File(...),
        access: ProjectAccess = Depends(require_planner),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        # The bound has to be answered before the body is read, not after.
        # Multipart parsing spools the whole upload to a temporary file before
        # this function is entered, so a limit applied to the resulting file
        # object had already let the transfer happen and the disk fill.
        _refuse_oversized_body(request)
        data = await _read_bounded(file)
        try:
            result = workspace.import_file(
                project_id,
                filename=file.filename or "upload.xml",
                data=data,
                actor_user_id=access.actor.user_id,
            )
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except ImportRefused as error:
            raise HTTPException(422, f"the file could not be read: {error}") from None
        except MigrationError as error:
            raise HTTPException(422, f"the file does not migrate: {error}") from None
        except StaleSchedule as error:
            raise HTTPException(409, str(error)) from None
        return schemas.ImportResponse(
            project_id=result.project_id,
            import_batch_id=result.import_batch_id,
            version_id=result.version_id,
            sequence=result.sequence,
            canonical_hash=result.canonical_hash,
            source_sha256=result.source_sha256,
            reconciliation=schemas.Reconciliation(
                matched=result.reconciliation.matched,
                new=result.reconciliation.new,
                rekeyed=result.reconciliation.rekeyed,
                missing=result.reconciliation.missing,
                guid_changed=result.reconciliation.guid_changed,
                guid_duplicated_in_snapshot=(
                    result.reconciliation.guid_duplicated_in_snapshot
                ),
            ),
            project_identity_mismatch=result.project_identity_mismatch,
            declared_project_guid=result.declared_project_guid,
            warnings=list(result.warnings),
        )

    @app.post(
        "/api/projects/{project_id}/calculations",
        response_model=schemas.CalculationSummary,
        status_code=201,
    )
    def calculate(
        project_id: uuid.UUID,
        access: ProjectAccess = Depends(require_planner),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        """Run the engine over the project's stored head and store the answer."""

        try:
            result = workspace.calculate(project_id, actor_user_id=access.actor.user_id)
        except NoSchedule:
            raise HTTPException(
                409, "the project has no schedule yet; import one before calculating"
            ) from None
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except StaleSchedule as error:
            raise HTTPException(409, str(error)) from None
        except (NetworkError, CalendarCompileError) as error:
            # The engine's whole refusal family, not PlanError alone. A
            # schedule that imported cleanly and then would not compile -- one
            # with no calendars, say -- came back as a server fault rather than
            # as the coded refusal this route promises.
            raise HTTPException(422, f"the schedule cannot be calculated: {error}") from None
        except IntegrityError as error:
            # Stored bytes that do not hash to what the row says. Nothing the
            # caller sent conflicts with anything, so this is a 500 like the
            # schedule route's, and the project is quarantined rather than
            # served a wrong answer.
            raise HTTPException(500, str(error)) from None
        return schemas.CalculationSummary(
            project_id=result.project_id,
            version_id=result.version_id,
            calculation_id=result.calculation_id,
            canonical_hash=result.canonical_hash,
            fingerprint=result.fingerprint,
            scheduled=result.scheduled,
            excluded=result.excluded,
            summaries=result.summaries,
            already_stored=result.already_stored,
        )

    @app.get(
        "/api/projects/{project_id}/calculations/latest",
        response_model=schemas.CalculationResponse,
    )
    def latest_calculation(
        project_id: uuid.UUID,
        access: ProjectAccess = Depends(require_viewer),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        """The stored calculation, every row as imported beside as calculated.

        The two sets of dates are kept apart: what the file said is never
        recomputed, and what this engine worked out is never written back over
        it. Comparing them is the point, and ``agrees_with_source`` says
        whether they match so a reader does not have to.
        """

        try:
            payload = workspace.latest_calculation(project_id)
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except IntegrityError as error:
            # Stored bytes that do not hash to what the row says. Nothing the
            # caller sent conflicts with anything, so this is a 500 like the
            # schedule route's, and the project is quarantined rather than
            # served a wrong answer.
            raise HTTPException(500, str(error)) from None
        if payload is None:
            raise HTTPException(404, "the project has no calculation yet")
        return schemas.CalculationResponse(**payload)

    @app.get(
        "/api/projects/{project_id}/planner",
        response_model=schemas.PlannerState,
    )
    def planner(
        project_id: uuid.UUID,
        access: ProjectAccess = Depends(require_viewer),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        try:
            return schemas.PlannerState(**workspace.planner_state(project_id))
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except NoSchedule:
            raise HTTPException(409, "the project has no imported schedule") from None
        except IntegrityError as error:
            raise HTTPException(500, str(error)) from None

    @app.post(
        "/api/projects/{project_id}/scenario",
        response_model=schemas.PlannerState,
        status_code=201,
    )
    def create_scenario(
        project_id: uuid.UUID,
        body: schemas.ScenarioEdit,
        access: ProjectAccess = Depends(require_planner),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        try:
            created = workspace.create_duration_scenario(
                project_id,
                expected_version_id=body.expected_version_id,
                activity_uid=body.activity_uid,
                planned_duration_seconds=body.planned_duration_seconds,
                actor_user_id=access.actor.user_id,
            )
            state = workspace.planner_state(project_id)
            scenario = state.get("scenario")
            change = state.get("change")
            if (
                state.get("current_version_id") != created.scenario_version_id
                or scenario is None
                or scenario.get("calculation_id") != created.calculation_id
                or change is None
                or change.get("scenario_version_id") != created.scenario_version_id
            ):
                raise StaleSchedule(
                    "the scenario was superseded before it could be returned; reload"
                )
            return schemas.PlannerState(**state)
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except NoSchedule:
            raise HTTPException(409, "the project has no imported schedule") from None
        except StaleSchedule as error:
            raise HTTPException(409, str(error)) from None
        except ScenarioRejected as error:
            raise HTTPException(
                422, {"code": error.code, "message": error.detail}
            ) from None
        except (NetworkError, CalendarCompileError) as error:
            raise HTTPException(422, f"the scenario cannot be calculated: {error}") from None
        except IntegrityError as error:
            raise HTTPException(500, str(error)) from None

    @app.post(
        "/api/projects/{project_id}/scenario/reset",
        response_model=schemas.ScenarioResetResponse,
    )
    def reset_scenario(
        project_id: uuid.UUID,
        body: schemas.ScenarioReset,
        access: ProjectAccess = Depends(require_planner),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        try:
            restored = workspace.reset_scenario(
                project_id,
                expected_version_id=body.expected_version_id,
                actor_user_id=access.actor.user_id,
            )
            state = workspace.planner_state(project_id)
            baseline = state.get("baseline")
            if (
                state.get("project_id") != restored.project_id
                or state.get("current_kind") != "baseline"
                or state.get("current_version_id") != restored.baseline_version_id
                or state.get("scenario") is not None
                or state.get("change") is not None
                or (restored.calculation_id is None) != (baseline is None)
                or (
                    baseline is not None
                    and (
                        baseline.get("version_id") != restored.baseline_version_id
                        or baseline.get("calculation_id") != restored.calculation_id
                        or baseline.get("fingerprint") != restored.fingerprint
                    )
                )
            ):
                raise StaleSchedule(
                    "the restored baseline was superseded before it could be returned; reload"
                )
            return schemas.ScenarioResetResponse(
                **state,
                reset_performed=restored.reset_performed,
                reset_event_id=restored.reset_event_id,
            )
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except NoSchedule:
            raise HTTPException(409, "the project has no imported schedule") from None
        except StaleSchedule as error:
            raise HTTPException(409, str(error)) from None
        except IntegrityError as error:
            raise HTTPException(500, str(error)) from None

    @app.get("/api/projects/{project_id}/scenario/export")
    def export_scenario(
        project_id: uuid.UUID,
        access: ProjectAccess = Depends(require_viewer),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        try:
            payload = workspace.scenario_export(project_id)
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except NoSchedule:
            raise HTTPException(409, "the project has no imported schedule") from None
        except ScenarioRejected as error:
            raise HTTPException(
                422, {"code": error.code, "message": error.detail}
            ) from None
        except IntegrityError as error:
            raise HTTPException(500, str(error)) from None
        return JSONResponse(
            jsonable_encoder(payload),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="sto-scenario-{project_id}.json"'
                )
            },
        )

    @app.get("/api/projects/{project_id}/schedule", response_model=schemas.ScheduleResponse)
    def get_schedule(
        project_id: uuid.UUID,
        include: str | None = None,
        access: ProjectAccess = Depends(require_viewer),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        try:
            working = workspace.load(project_id)
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except IntegrityError as error:
            raise HTTPException(500, str(error)) from None
        if working is None:
            raise HTTPException(404, "the project has no schedule yet")
        document = None
        if include == "document":
            from sto.core.model.codec import encode_schedule

            document = encode_schedule(working.schedule)
        return schemas.ScheduleResponse(
            project_id=project_id,
            version_id=working.version_id,
            sequence=working.sequence,
            canonical_hash=working.canonical_hash,
            schedule_id=working.schedule.schedule_id,
            counts=working.schedule.counts(),
            document=document,
        )

    @app.get(
        "/api/projects/{project_id}/memberships",
        response_model=list[schemas.MembershipResponse],
    )
    def list_memberships(
        project_id: uuid.UUID,
        access: ProjectAccess = Depends(require_admin_read),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        with workspace.connect() as conn:
            return [
                schemas.MembershipResponse(**row)
                for row in auth_repo.list_memberships(conn, project_id=project_id)
            ]

    @app.post(
        "/api/projects/{project_id}/memberships",
        response_model=schemas.MembershipResponse,
    )
    def grant_membership(
        project_id: uuid.UUID,
        body: schemas.MembershipGrant,
        access: ProjectAccess = Depends(require_admin),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        with workspace.connect() as conn:
            user = auth_repo.get_user(conn, body.user_id)
            if user is None or not user["enabled"]:
                raise HTTPException(404, "no such enabled user")
            try:
                row = auth_repo.grant_membership(
                    conn,
                    project_id=project_id,
                    user_id=body.user_id,
                    role=body.role,
                    created_by_user_id=access.actor.user_id,
                )
            except auth_repo.LastProjectAdministrator as error:
                raise HTTPException(409, str(error)) from None
            except auth_repo.DisabledUser:
                raise HTTPException(404, "no such enabled user") from None
            conn.commit()
        return schemas.MembershipResponse(
            **row,
            username=user["username"],
            display_name=user["display_name"],
            enabled=user["enabled"],
        )

    @app.delete(
        "/api/projects/{project_id}/memberships/{user_id}",
        status_code=204,
    )
    def revoke_membership(
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        response: Response,
        access: ProjectAccess = Depends(require_admin),
        workspace: Workspace = Depends(ws),
    ) -> Response:
        with workspace.connect() as conn:
            try:
                revoked = auth_repo.revoke_membership(
                    conn,
                    project_id=project_id,
                    user_id=user_id,
                    actor_user_id=access.actor.user_id,
                )
            except auth_repo.LastProjectAdministrator as error:
                raise HTTPException(409, str(error)) from None
            if revoked is None:
                raise HTTPException(404, "no active project membership")
            conn.commit()
        response.status_code = 204
        return response

    @app.get(
        "/api/projects/{project_id}/device-tokens",
        response_model=list[schemas.DeviceTokenResponse],
    )
    def list_device_tokens(
        project_id: uuid.UUID,
        access: ProjectAccess = Depends(require_admin_read),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        with workspace.connect() as conn:
            return [
                schemas.DeviceTokenResponse(**row)
                for row in auth_repo.list_device_tokens(conn, project_id=project_id)
            ]

    @app.post(
        "/api/projects/{project_id}/device-tokens",
        response_model=schemas.DeviceTokenResponse,
        status_code=201,
    )
    def issue_device_token(
        project_id: uuid.UUID,
        body: schemas.DeviceTokenIssue,
        response: Response,
        access: ProjectAccess = Depends(require_admin),
        service: AuthService = Depends(auth),
    ) -> Any:
        expires = (
            None
            if body.expires_in_days is None
            else service.now() + timedelta(days=body.expires_in_days)
        )
        try:
            result = service.issue_device_token(
                issuer=access.actor,
                project_id=project_id,
                user_id=body.user_id,
                role=body.role,
                expires_at=expires,
            )
        except AuthorizationFailed:
            raise HTTPException(403, "device token authority exceeds membership") from None
        response.headers["Cache-Control"] = "no-store"
        return schemas.DeviceTokenResponse(**result.row, raw_token=result.raw_token)

    @app.delete("/api/projects/{project_id}/device-tokens/{token_id}", status_code=204)
    def revoke_device_token(
        project_id: uuid.UUID,
        token_id: uuid.UUID,
        response: Response,
        access: ProjectAccess = Depends(require_admin),
        workspace: Workspace = Depends(ws),
    ) -> Response:
        with workspace.connect() as conn:
            revoked = auth_repo.revoke_device_token(
                conn, project_id=project_id, token_id=token_id
            )
            conn.commit()
        if not revoked:
            raise HTTPException(404, "no active device token")
        response.status_code = 204
        return response

    @app.get("/", include_in_schema=False)
    def index() -> Any:
        """The read-only view of a stored calculation.

        Mounted rather than templated: the page is three static files that
        fetch two routes, so what it can show is exactly what the API returns
        and there is no second rendering of the same numbers to disagree.
        """

        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/projects/{project_id}/versions", response_model=list[schemas.ScheduleHead])
    def list_versions(
        project_id: uuid.UUID,
        access: ProjectAccess = Depends(require_viewer),
        workspace: Workspace = Depends(ws),
    ) -> Any:
        with workspace.connect() as conn:
            if repo.get_project(conn, project_id) is None:
                raise HTTPException(404, "no such project")
            rows = repo.list_versions(conn, project_id=project_id)
        return [_head(row) for row in rows]

    inventory: dict[tuple[str, str], str] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())
        if path == "/healthz":
            category = "OPERATIONAL LIVENESS"
        elif path == "/api/auth/login":
            category = "PUBLIC AUTH BOOTSTRAP"
        elif path.startswith("/api/projects/{project_id}"):
            category = (
                "PROJECT-SCOPED READ"
                if methods <= {"GET", "HEAD"}
                else "PROJECT-SCOPED WRITE"
            )
        elif path.startswith("/api/"):
            category = "AUTHENTICATED"
        else:
            continue
        for method in methods:
            if method not in {"HEAD", "OPTIONS"}:
                inventory[(method, path)] = category
    app.state.route_inventory = inventory

    app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _head(row: dict[str, Any] | None) -> schemas.ScheduleHead | None:
    if row is None:
        return None
    return schemas.ScheduleHead(
        version_id=row["id"],
        sequence=row["sequence"],
        kind=row["kind"],
        canonical_hash=row["canonical_hash"],
        schema_version=row["schema_version"],
        engine_profile=row["engine_profile"],
        cause_type=row["cause_type"],
        created_at=row["created_at"],
    )


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, workers=1)
