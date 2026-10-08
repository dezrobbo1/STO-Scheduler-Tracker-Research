#!/usr/bin/env python3
"""Create disposable PL5 authority and schedule data for cloud Android CI.

The raw device credentials are written only to STO_EMULATOR_SETUP_FILE on the
ephemeral runner. They must never be printed or uploaded as evidence.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

from sto.api.auth import Actor, AuthService
from sto.persistence import auth_repositories as auth_repo
from sto.persistence import repositories as repo
from sto.persistence.db import connect
from sto.scheduling.working_schedule import Workspace

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"
SETUP = Path(os.environ["STO_EMULATOR_SETUP_FILE"])
SOURCE_DIR = Path(os.environ["STO_SOURCE_DIR"])

ACTIVITIES = {
    "isolate": "0d717f24-85ff-5d98-afce-2fcaf8bbb5cf",
    "inspect": "1256e448-70c8-5839-8a89-9300d703d276",
    "restore": "88f5407a-79c8-5501-a94a-50d91104ac0d",
}


def create_member(service: AuthService, username: str, display_name: str) -> dict:
    # These credentials exist only in the ephemeral CI database. Device access
    # below uses independently generated project-scoped bearer credentials.
    return service.create_user(
        username=username,
        password="synthetic-cloud-emulator-password",
        totp_secret="JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        display_name=display_name,
    )


def main() -> int:
    service = AuthService.from_environment(connect=connect)
    admin = create_member(service, "emu-admin", "Emulator Admin")
    device_a = create_member(service, "emu-device-a", "Emulator Device A")
    device_b = create_member(service, "emu-device-b", "Emulator Device B")

    with connect() as conn:
        project = repo.create_project(
            conn,
            name="PL5 Android Cloud Emulator",
            timezone="UTC",
            description="Disposable CI-only PL5 emulator project",
            created_by_user_id=admin["id"],
        )
        auth_repo.grant_membership(
            conn,
            project_id=project["id"],
            user_id=admin["id"],
            role="admin",
            created_by_user_id=admin["id"],
        )
        for member in (device_a, device_b):
            auth_repo.grant_membership(
                conn,
                project_id=project["id"],
                user_id=member["id"],
                role="planner",
                created_by_user_id=admin["id"],
            )
        conn.commit()

    workspace = Workspace(connect=connect, source_dir=SOURCE_DIR)
    imported = workspace.import_file(
        project["id"],
        filename=FIXTURE.name,
        data=FIXTURE.read_bytes(),
        actor_user_id=admin["id"],
    )
    calculation = workspace.calculate(project["id"], actor_user_id=admin["id"])

    issuer = Actor(
        user_id=admin["id"],
        username=admin["username"],
        display_name=admin["display_name"],
        authentication="browser",
    )
    expires_at = service.now() + timedelta(days=1)
    issued_a = service.issue_device_token(
        issuer=issuer,
        project_id=project["id"],
        user_id=device_a["id"],
        role="planner",
        expires_at=expires_at,
    )
    issued_b = service.issue_device_token(
        issuer=issuer,
        project_id=project["id"],
        user_id=device_b["id"],
        role="planner",
        expires_at=expires_at,
    )

    with connect() as conn:
        cursor = repo.live_cursor(conn, project["id"])
    if cursor != 0:
        raise RuntimeError(f"disposable emulator project did not start at cursor zero: {cursor}")

    payload = {
        "project_id": str(project["id"]),
        "baseline_version_id": str(imported.version_id),
        "baseline_hash": imported.canonical_hash,
        "calculation_id": str(calculation.calculation_id),
        "calculation_fingerprint": calculation.fingerprint,
        "actor_a": str(device_a["id"]),
        "actor_b": str(device_b["id"]),
        "credential_a_id": str(issued_a.row["id"]),
        "credential_b_id": str(issued_b.row["id"]),
        "credential_a": issued_a.raw_token,
        "credential_b": issued_b.raw_token,
        "activities": ACTIVITIES,
        "server_sha": os.environ["STO_BUILD_SHA"],
    }
    SETUP.parent.mkdir(parents=True, exist_ok=True)
    SETUP.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    SETUP.chmod(0o600)

    print(
        "PL5 cloud-emulator setup ready: "
        f"project={payload['project_id']} baseline={payload['baseline_version_id']} "
        f"actor_a={payload['actor_a']} actor_b={payload['actor_b']} cursor=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
