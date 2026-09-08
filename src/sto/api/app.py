"""FastAPI application. One worker, one process, one resident workspace.

Boot rebuilds every project's baseline head from the database and verifies its
hash. That is the persistence gate in operational form: if a restart cannot
reproduce what it stored, the process does not come up quietly.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

#: The largest upload this API will read. A schedule of CALCINER's size is
#: fourteen megabytes; the legacy workspace already refused past sixty-four,
#: and reading an unbounded body into memory on the one worker that also does
#: the parsing is how a single request takes the process with it.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

#: The read-only page, beside this module so that packaging carries it.
STATIC_DIR = Path(__file__).with_name("static")

from sto.core.model.migrate.sto_v011 import MigrationError
from sto.persistence import repositories as repo
from sto.persistence.db import connect
from sto.core.engine import PlanError
from sto.scheduling.working_schedule import (
    ImportRefused,
    IntegrityError,
    UnknownProject,
    Workspace,
)

from . import schemas

#: 8090 is the Java API until cut-over (frozen-repository deployment); the new
#: stack is trialled beside it. The port swaps at PL12, not before.
DEFAULT_PORT = 8092


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
        project_id: uuid.UUID,
        file: UploadFile = File(...),
        workspace: Workspace = Depends(ws),
    ) -> Any:
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
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
        except IntegrityError as error:
            raise HTTPException(409, str(error)) from None
        except PlanError as error:
            raise HTTPException(422, f"the schedule cannot be planned: {error}") from None
        return schemas.CalculationSummary(
            project_id=result.project_id,
            version_id=result.version_id,
            calculation_id=result.calculation_id,
            canonical_hash=result.canonical_hash,
            fingerprint=result.fingerprint,
            scheduled=result.scheduled,
            excluded=result.excluded,
            summaries=result.summaries,
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
            raise HTTPException(409, str(error)) from None
        if payload is None:
            raise HTTPException(404, "the project has no calculation yet")
        return schemas.CalculationResponse(**payload)

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
