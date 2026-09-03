"""FastAPI application. One worker, one process, one resident workspace.

Boot rebuilds every project's baseline head from the database and verifies its
hash. That is the persistence gate in operational form: if a restart cannot
reproduce what it stored, the process does not come up quietly.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile

from sto.core.model.migrate.sto_v011 import MigrationError
from sto.persistence import repositories as repo
from sto.persistence.db import connect
from sto.scheduling.working_schedule import IntegrityError, UnknownProject, Workspace

from . import schemas

#: 8090 is the Java API until cut-over (frozen-repository deployment); the new
#: stack is trialled beside it. The port swaps at PL12, not before.
DEFAULT_PORT = 8092


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
        data = await file.read()
        try:
            result = workspace.import_file(
                project_id, filename=file.filename or "upload.xml", data=data
            )
        except UnknownProject:
            raise HTTPException(404, "no such project") from None
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
            ),
            project_identity_mismatch=result.project_identity_mismatch,
            declared_project_guid=result.declared_project_guid,
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

    @app.get("/api/projects/{project_id}/versions", response_model=list[schemas.ScheduleHead])
    def list_versions(project_id: uuid.UUID, workspace: Workspace = Depends(ws)) -> Any:
        with workspace.connect() as conn:
            if repo.get_project(conn, project_id) is None:
                raise HTTPException(404, "no such project")
            rows = repo.list_versions(conn, project_id=project_id)
        return [_head(row) for row in rows]

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
