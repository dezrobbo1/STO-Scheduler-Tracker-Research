#!/usr/bin/env python3
"""Serve the disposable PL5 cloud-emulator API over ephemeral CI TLS."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from sto.api.app import create_app
from sto.api.auth import AuthService
from sto.persistence.db import connect
from sto.scheduling.working_schedule import Workspace


def main() -> int:
    cert = Path(os.environ["STO_EMULATOR_TLS_CERT"])
    key = Path(os.environ["STO_EMULATOR_TLS_KEY"])
    if not cert.is_file() or not key.is_file():
        raise RuntimeError("cloud-emulator TLS material is unavailable")

    workspace = Workspace(connect=connect)
    workspace.rebuild()
    auth = AuthService.from_environment(connect=connect)
    app = create_app(workspace, auth)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8443,
        workers=1,
        ssl_certfile=str(cert),
        ssl_keyfile=str(key),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
