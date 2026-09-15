"""Synthetic, deterministic authentication for PostgreSQL API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pyotp
from fastapi.testclient import TestClient

from sto.api.app import create_app
from sto.api.auth import AuthService


class AuthTestContext:
    """One persisted user and monotonically consumed controlled TOTP counters."""

    password = "synthetic-auth-test-password"
    secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

    def __init__(self, *, connect, username: str = "test-planner") -> None:
        self.current = datetime(2035, 1, 1, 9, 0, tzinfo=UTC)
        self.service = AuthService.for_tests(connect=connect, now=lambda: self.current)
        self.user = self.service.create_user(
            username=username,
            password=self.password,
            totp_secret=self.secret,
            display_name="Synthetic Planner",
        )

    def login(self, client: TestClient) -> dict[str, Any]:
        otp = pyotp.TOTP(self.secret).at(self.current)
        response = client.post(
            "/api/auth/login",
            json={"username": self.user["username"], "password": self.password, "totp": otp},
        )
        if response.status_code != 200:
            raise AssertionError(response.text)
        session = response.json()
        client.headers["X-CSRF-Token"] = session["csrf_token"]
        self.current += timedelta(seconds=30)
        return session

    def client(self, workspace) -> TestClient:
        client = TestClient(create_app(workspace, self.service))
        self.login(client)
        return client
