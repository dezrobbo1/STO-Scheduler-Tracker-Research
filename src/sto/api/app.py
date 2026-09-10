"""FastAPI application. One worker, one process, one resident workspace.

Boot rebuilds every project's baseline head from the database and verifies its
hash. That is the persistence gate in operational form: if a restart cannot
reproduce what it stored, the process does not come up quietly.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
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


def create_app(workspace: Workspace | None = None) -> FastAPI:
    workspace = workspace or Workspace(connect=connect)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.resident = workspace.rebuild()
        yield

    app = FastAPI(title="STO", version="0.1", lifespan=lifespan)
    app.state.workspace = workspace
    # Below the multipart parser, so an oversized body is refused while it is
    # arriving rather than after it has been spooled.
    app.add_middleware(BoundedBody, limit=MAX_UPLOAD_BYTES + _MULTIPART_ALLOWANCE)


    def ws(request: Request) -> Workspace:
        return request.app.state.workspace

    @app.get("/api/health", response_model=schemas.Health)
    def health(workspace: Workspace = Depends(ws)) -> Any:
        try:
            with workspace.connect() as conn:
                conn.execute("SELECT 1")
            database = "ok"
        except Exception as error:  # noqa: BLE001 - reported, not hidden
            database = f"error: {type(error).__name__}"
        failures = dict(workspace.integrity_failures)
        return schemas.Health(
            status="ok" if database == "ok" and not failures else "degraded",
            database=database,
            resident_projects=len(workspace.resident_ids()),
            integrity_failures=failures,
        )

    @app.post("/api/projects", response_model=schemas.Project, status_code=201)
    def create_project(body: schemas.ProjectCreate, workspace: Workspace = Depends(ws)) -> Any:
        with workspace.connect() as conn:
            row = repo.create_project(
                conn, name=body.name, timezone=body.timezone, description=body.description
            )
            conn.commit()
        return schemas.Project(**row)

    @app.get("/api/projects", response_model=list[schemas.Project])
    def list_projects(workspace: Workspace = Depends(ws)) -> Any:
        with workspace.connect() as conn:
            rows = repo.list_projects(conn)
            heads = {
                h["project_id"]: h
                for h in repo.heads_for_all_projects(conn)
                if h["head_kind"] == "baseline"
            }
        return [schemas.Project(**row, baseline=_head(heads.get(row["id"]))) for row in rows]

    @app.get("/api/projects/{project_id}", response_model=schemas.Project)
    def get_project(project_id: uuid.UUID, workspace: Workspace = Depends(ws)) -> Any:
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
                project_id, filename=file.filename or "upload.xml", data=data
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
    def calculate(project_id: uuid.UUID, workspace: Workspace = Depends(ws)) -> Any:
        """Run the engine over the project's stored head and store the answer."""

        try:
            result = workspace.calculate(project_id)
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
    def latest_calculation(project_id: uuid.UUID, workspace: Workspace = Depends(ws)) -> Any:
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
    def planner(project_id: uuid.UUID, workspace: Workspace = Depends(ws)) -> Any:
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
        workspace: Workspace = Depends(ws),
    ) -> Any:
        try:
            created = workspace.create_duration_scenario(
                project_id,
                expected_version_id=body.expected_version_id,
                activity_uid=body.activity_uid,
                planned_duration_seconds=body.planned_duration_seconds,
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
        response_model=schemas.PlannerState,
    )
    def reset_scenario(
        project_id: uuid.UUID,
        body: schemas.ScenarioReset,
        workspace: Workspace = Depends(ws),
    ) -> Any:
        try:
            workspace.reset_scenario(
                project_id, expected_version_id=body.expected_version_id
            )
            return schemas.PlannerState(**workspace.planner_state(project_id))
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
        project_id: uuid.UUID, workspace: Workspace = Depends(ws)
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
        project_id: uuid.UUID, include: str | None = None, workspace: Workspace = Depends(ws)
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

    @app.get("/", include_in_schema=False)
    def index() -> Any:
        """The read-only view of a stored calculation.

        Mounted rather than templated: the page is three static files that
        fetch two routes, so what it can show is exactly what the API returns
        and there is no second rendering of the same numbers to disagree.
        """

        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/projects/{project_id}/versions", response_model=list[schemas.ScheduleHead])
    def list_versions(project_id: uuid.UUID, workspace: Workspace = Depends(ws)) -> Any:
        with workspace.connect() as conn:
            if repo.get_project(conn, project_id) is None:
                raise HTTPException(404, "no such project")
            rows = repo.list_versions(conn, project_id=project_id)
        return [_head(row) for row in rows]

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
