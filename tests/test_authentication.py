"""PL2: a real actor and project boundary around every application route."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

REQUIRE_DB = os.environ.get("STO_REQUIRE_DB") == "1"
ADMIN_URL = os.environ.get(
    "STO_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5433/postgres"
)
ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "infra" / "migrations"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic-workspace-chain.mspdi.xml"

try:
    import psycopg
    import pyotp
    from fastapi.testclient import TestClient
except ImportError as error:
    if REQUIRE_DB:
        raise RuntimeError(
            f"STO_REQUIRE_DB=1 but the api/test extras are missing ({error.name})"
        ) from error
    psycopg = None  # type: ignore[assignment]
    pyotp = None  # type: ignore[assignment]
    TestClient = None  # type: ignore[assignment,misc]


def _reachable() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            return True
    except psycopg.OperationalError as error:
        if REQUIRE_DB:
            raise RuntimeError(
                f"STO_REQUIRE_DB=1 but {ADMIN_URL} is unreachable: {error}"
            ) from error
        return False


@unittest.skipUnless(
    _reachable(),
    "PostgreSQL or api/test extras unavailable; STO_REQUIRE_DB=1 makes this a failure",
)
class AuthenticationBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sto.api.auth import AuthService
        from sto.persistence.db import connect

        cls.dbname = f"sto_auth_{secrets.token_hex(4)}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{cls.dbname}"')
        cls.url = ADMIN_URL.rsplit("/", 1)[0] + "/" + cls.dbname
        with psycopg.connect(cls.url) as conn:
            for path in sorted(MIGRATIONS.glob("V*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))
            conn.commit()
        cls.connect = staticmethod(lambda url=cls.url: connect(url))
        cls.current = datetime(2035, 2, 3, 10, 0, tzinfo=UTC)
        cls.auth = AuthService.for_tests(connect=cls.connect, now=lambda: cls.current)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{cls.dbname}" WITH (FORCE)')

    @classmethod
    def advance(cls, seconds: int = 30) -> None:
        cls.current += timedelta(seconds=seconds)

    def user(self, label: str = "user"):
        username = f"{label}-{uuid.uuid4().hex[:10]}"
        secret = base64.b32encode(hashlib.sha256(username.encode()).digest()).decode()
        row = self.auth.create_user(
            username=username,
            password="synthetic-password-only",
            totp_secret=secret,
            display_name=f"Synthetic {label}",
        )
        return row, secret

    def app_client(self):
        from sto.api.app import create_app
        from sto.scheduling.working_schedule import Workspace

        workspace = Workspace(connect=self.connect, source_dir=Path(self.tmp.name))
        client = TestClient(create_app(workspace, self.auth))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def login(self, client, row, secret, *, advance: bool = True):
        otp = pyotp.TOTP(secret).at(self.current)
        response = client.post(
            "/api/auth/login",
            json={
                "username": row["username"],
                "password": "synthetic-password-only",
                "totp": otp,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        if advance:
            self.advance()
        return response, otp

    def authenticated(self, label="user"):
        row, secret = self.user(label)
        client = self.app_client()
        response, _ = self.login(client, row, secret)
        return client, row, secret, response

    def project_with_scenario(self, client, name="authorized"):
        created = client.post("/api/projects", json={"name": name})
        self.assertEqual(created.status_code, 201, created.text)
        project = created.json()["id"]
        imported = client.post(
            f"/api/projects/{project}/imports",
            files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "application/xml")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        calculated = client.post(f"/api/projects/{project}/calculations")
        self.assertEqual(calculated.status_code, 201, calculated.text)
        state = client.get(f"/api/projects/{project}/planner").json()
        target = state["eligible_activities"][0]
        scenario = client.post(
            f"/api/projects/{project}/scenario",
            json={
                "expected_version_id": state["current_version_id"],
                "activity_uid": target["activity_uid"],
                "planned_duration_seconds": target["planned_duration_seconds"] + 3600,
            },
        )
        self.assertEqual(scenario.status_code, 201, scenario.text)
        return project, scenario.json()

    def grant(self, admin, project, user, role):
        response = admin.post(
            f"/api/projects/{project}/memberships",
            json={"user_id": str(user["id"]), "role": role},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_configuration_fails_closed_without_a_master_key(self):
        from sto.api.auth import AuthConfig, AuthenticationConfigurationError

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AuthenticationConfigurationError):
                AuthConfig.from_environment()

    def test_password_totp_and_replay_are_real_and_generic(self):
        row, secret = self.user("credentials")
        client = self.app_client()
        otp = pyotp.TOTP(secret).at(self.current)
        totp = pyotp.TOTP(secret)
        current_counter = int(self.current.timestamp()) // 30
        valid_window = {
            totp.at(counter * 30)
            for counter in range(current_counter - 1, current_counter + 2)
        }
        wrong_code = next(
            f"{number:06d}"
            for number in range(1_000_000)
            if f"{number:06d}" not in valid_window
        )
        bad_password = client.post(
            "/api/auth/login",
            json={"username": row["username"], "password": "wrong-password", "totp": otp},
        )
        bad_otp = client.post(
            "/api/auth/login",
            json={
                "username": row["username"],
                "password": "synthetic-password-only",
                "totp": wrong_code,
            },
        )
        missing = client.post(
            "/api/auth/login",
            json={
                "username": "not-a-user",
                "password": "synthetic-password-only",
                "totp": otp,
            },
        )
        self.assertEqual(
            [bad_password.status_code, bad_otp.status_code, missing.status_code],
            [401, 401, 401],
        )
        self.assertEqual(bad_password.json(), bad_otp.json())
        self.assertEqual(bad_password.json(), missing.json())

        accepted, consumed = self.login(client, row, secret, advance=False)
        cookie = accepted.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Max-Age=", cookie)
        raw_session = client.cookies.get(self.auth.config.cookie_name)
        replay = self.app_client().post(
            "/api/auth/login",
            json={
                "username": row["username"],
                "password": "synthetic-password-only",
                "totp": consumed,
            },
        )
        self.assertEqual(replay.status_code, 401)
        self.advance()

        with self.connect() as conn:
            stored = conn.execute(
                "SELECT password_hash, totp_secret_encrypted FROM users WHERE id=%s",
                (row["id"],),
            ).fetchone()
            session_row = conn.execute(
                "SELECT token_hash, token_prefix FROM server_sessions WHERE user_id=%s",
                (row["id"],),
            ).fetchone()
        self.assertTrue(stored["password_hash"].startswith("$argon2id$"))
        self.assertNotIn(b"synthetic-password-only", stored["totp_secret_encrypted"])
        self.assertNotIn(secret.encode(), stored["totp_secret_encrypted"])
        self.assertNotEqual(session_row["token_hash"], raw_session)
        self.assertNotIn(raw_session, str(session_row))

    def test_enrollment_and_login_share_exact_credential_limits(self):
        from sto.api.auth import AuthService

        secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
        exact_username = "u" * 200
        exact_password = "p" * 1024
        row = self.auth.create_user(
            username=exact_username,
            password=exact_password,
            totp_secret=secret,
        )
        client = self.app_client()
        exact = client.post(
            "/api/auth/login",
            json={
                "username": exact_username,
                "password": exact_password,
                "totp": pyotp.TOTP(secret).at(self.current),
            },
        )
        self.assertEqual(exact.status_code, 200, exact.text)
        self.advance()

        minimum_password = "m" * 12
        minimum_username = self.auth.create_user(
            username="q",
            password=minimum_password,
            totp_secret=secret,
        )
        self.assertEqual(minimum_username["normalized_username"], "q")
        normalized_label = uuid.uuid4().hex[:10]
        normalized = self.auth.create_user(
            username=f"  Ａlice-{normalized_label}  ",
            password=minimum_password,
            totp_secret=secret,
        )
        normalized_login = client.post(
            "/api/auth/login",
            json={
                "username": f"alice-{normalized_label}",
                "password": minimum_password,
                "totp": pyotp.TOTP(secret).at(self.current),
            },
        )
        self.assertEqual(normalized_login.status_code, 200, normalized_login.text)
        self.assertEqual(normalized["normalized_username"], f"alice-{normalized_label}")

        with self.connect() as conn:
            before = conn.execute("SELECT count(*) AS count FROM users").fetchone()[
                "count"
            ]
        for username, password in (
            ("u" * 201, minimum_password),
            (f"password-too-long-{uuid.uuid4().hex}", "p" * 1025),
            (" \u3000 ", minimum_password),
            (f"password-too-short-{uuid.uuid4().hex}", "p" * 11),
        ):
            with self.subTest(username_length=len(username), password_length=len(password)):
                with self.assertRaises(ValueError):
                    self.auth.create_user(
                        username=username,
                        password=password,
                        totp_secret=secret,
                    )
        with self.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) AS count FROM users").fetchone()["count"],
                before,
            )

        for username, password in (
            ("u" * 201, minimum_password),
            (row["username"], "p" * 1025),
            (" \u3000 ", minimum_password),
            (row["username"], "p" * 11),
        ):
            with self.subTest(
                login_username_length=len(username),
                login_password_length=len(password),
            ):
                refused = client.post(
                    "/api/auth/login",
                    json={"username": username, "password": password, "totp": "123456"},
                )
                self.assertEqual(refused.status_code, 422, refused.text)

        class HashSpy:
            def __init__(self):
                self.calls = []

            def hash(self, password):
                self.calls.append(password)
                return "$argon2id$synthetic"

        spy = HashSpy()
        validating = AuthService(
            connect=self.connect,
            config=self.auth.config,
            password_hasher=spy,  # type: ignore[arg-type]
        )
        spy.calls.clear()  # discard construction of the timing dummy hash
        with self.assertRaises(ValueError):
            validating.create_user(
                username="u" * 201,
                password=minimum_password,
                totp_secret=secret,
            )
        with self.assertRaises(ValueError):
            validating.bootstrap_admin(username="valid-name", password="p" * 1025)
        self.assertEqual(spy.calls, [])

    def test_failed_and_concurrent_bootstrap_are_atomic(self):
        from sto.api.auth import AuthService, BootstrapClosed
        from sto.persistence.db import connect

        dbname = f"sto_bootstrap_{secrets.token_hex(4)}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{dbname}"')
        url = ADMIN_URL.rsplit("/", 1)[0] + "/" + dbname
        try:
            with psycopg.connect(url) as conn:
                for path in sorted(MIGRATIONS.glob("V*.sql")):
                    conn.execute(path.read_text(encoding="utf-8"))
                conn.commit()
            connection = lambda: connect(url)  # noqa: E731 - injected factory
            service = AuthService.for_tests(connect=connection)
            with self.assertRaises(ValueError):
                service.bootstrap_admin(username="b" * 201, password="p" * 12)
            with connection() as conn:
                self.assertEqual(
                    conn.execute("SELECT count(*) AS count FROM users").fetchone()[
                        "count"
                    ],
                    0,
                )

            ready = threading.Barrier(2)

            def bootstrap(label):
                ready.wait(timeout=10)
                try:
                    row, secret, uri = service.bootstrap_admin(
                        username=f"bootstrap-{label}", password="p" * 12
                    )
                    return ("created", row["id"], bool(secret), uri.startswith("otpauth://"))
                except BootstrapClosed:
                    return ("closed", None, False, False)

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = [
                    future.result(timeout=20)
                    for future in (
                        pool.submit(bootstrap, "first"),
                        pool.submit(bootstrap, "second"),
                    )
                ]
            self.assertEqual([row[0] for row in outcomes].count("created"), 1)
            self.assertEqual([row[0] for row in outcomes].count("closed"), 1)
            created = next(row for row in outcomes if row[0] == "created")
            self.assertTrue(created[2])
            self.assertTrue(created[3])
            with connection() as conn:
                self.assertEqual(
                    conn.execute("SELECT count(*) AS count FROM users").fetchone()[
                        "count"
                    ],
                    1,
                )
        finally:
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')

    def test_every_application_route_rejects_anonymous_requests_and_has_a_guard(self):
        client = self.app_client()
        marker = uuid.uuid4()
        requests = {
            ("GET", "/api/auth/session"): {},
            ("POST", "/api/auth/logout"): {},
            ("GET", "/api/health"): {},
            ("GET", "/api/projects"): {},
            ("POST", "/api/projects"): {"json": {"name": "refused"}},
            ("GET", f"/api/projects/{marker}"): {},
            ("POST", f"/api/projects/{marker}/imports"): {
                "files": {"file": (FIXTURE.name, FIXTURE.read_bytes(), "application/xml")}
            },
            ("POST", f"/api/projects/{marker}/calculations"): {},
            ("GET", f"/api/projects/{marker}/calculations/latest"): {},
            ("GET", f"/api/projects/{marker}/planner"): {},
            ("POST", f"/api/projects/{marker}/scenario"): {
                "json": {
                    "expected_version_id": str(marker),
                    "activity_uid": str(marker),
                    "planned_duration_seconds": 3600,
                }
            },
            ("POST", f"/api/projects/{marker}/scenario/reset"): {
                "json": {"expected_version_id": str(marker)}
            },
            ("GET", f"/api/projects/{marker}/scenario/export"): {},
            ("GET", f"/api/projects/{marker}/schedule"): {},
            ("GET", f"/api/projects/{marker}/memberships"): {},
            ("POST", f"/api/projects/{marker}/memberships"): {
                "json": {"user_id": str(marker), "role": "viewer"}
            },
            ("DELETE", f"/api/projects/{marker}/memberships/{marker}"): {},
            ("GET", f"/api/projects/{marker}/device-tokens"): {},
            ("POST", f"/api/projects/{marker}/device-tokens"): {
                "json": {"user_id": str(marker), "role": "viewer"}
            },
            ("DELETE", f"/api/projects/{marker}/device-tokens/{marker}"): {},
            ("GET", f"/api/projects/{marker}/versions"): {},
        }
        for (method, path), kwargs in requests.items():
            with self.subTest(method=method, path=path):
                response = client.request(method, path, **kwargs)
                self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(client.get("/healthz").json(), {"status": "ok"})
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/openapi.json").status_code, 404)
        self.assertEqual(client.get("/docs").status_code, 404)

        def policies(dependant):
            found = []
            for child in dependant.dependencies:
                policy = getattr(child.call, "_sto_policy", None)
                if policy:
                    found.append(policy)
                found.extend(policies(child))
            return found

        for route in client.app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api/") or path == "/api/auth/login":
                continue
            with self.subTest(route=path):
                required = (
                    "project"
                    if path.startswith("/api/projects/{project_id}")
                    else "authenticated"
                )
                self.assertIn(required, policies(route.dependant))

    def test_csrf_is_bound_to_the_cookie_session(self):
        client, _, _, login = self.authenticated("csrf")
        self.assertEqual(client.get("/api/projects").status_code, 200)
        missing = client.post(
            "/api/projects",
            headers={"X-CSRF-Token": ""},
            json={"name": "missing-csrf"},
        )
        wrong = client.post(
            "/api/projects",
            headers={"X-CSRF-Token": "not-the-session-value"},
            json={"name": "wrong-csrf"},
        )
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(wrong.status_code, 403)
        accepted = client.post("/api/projects", json={"name": "valid-csrf"})
        self.assertEqual(accepted.status_code, 201, accepted.text)
        shown = client.get("/api/projects")
        self.assertEqual(shown.headers["cache-control"], "private, no-store")
        self.assertEqual(shown.headers["vary"], "Cookie, Authorization")

        other, _, _, other_login = self.authenticated("other-csrf")
        mismatch = client.post(
            "/api/projects",
            headers={"X-CSRF-Token": other_login.json()["csrf_token"]},
            json={"name": "cross-session-csrf"},
        )
        self.assertEqual(mismatch.status_code, 403)

    def test_cross_user_project_isolation_and_viewer_matrix(self):
        admin, user_a, _, _ = self.authenticated("project-admin")
        viewer, user_b, _, _ = self.authenticated("outsider")
        project, scenario = self.project_with_scenario(admin)

        self.assertEqual(viewer.get("/api/projects").json(), [])
        for path in (
            f"/api/projects/{project}",
            f"/api/projects/{project}/schedule",
            f"/api/projects/{project}/versions",
            f"/api/projects/{project}/calculations/latest",
            f"/api/projects/{project}/planner",
            f"/api/projects/{project}/scenario/export",
        ):
            with self.subTest(absent=path):
                self.assertEqual(viewer.get(path).status_code, 404)
        target = scenario["eligible_activities"][0]
        forbidden_without_membership = (
            viewer.post(
                f"/api/projects/{project}/imports",
                files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "application/xml")},
            ),
            viewer.post(f"/api/projects/{project}/calculations"),
            viewer.post(
                f"/api/projects/{project}/scenario",
                json={
                    "expected_version_id": scenario["current_version_id"],
                    "activity_uid": target["activity_uid"],
                    "planned_duration_seconds": target["planned_duration_seconds"] + 3600,
                },
            ),
            viewer.post(
                f"/api/projects/{project}/scenario/reset",
                json={"expected_version_id": scenario["current_version_id"]},
            ),
        )
        self.assertEqual([r.status_code for r in forbidden_without_membership], [404] * 4)

        self.grant(admin, project, user_b, "viewer")
        self.assertEqual([row["id"] for row in viewer.get("/api/projects").json()], [project])
        for path in (
            f"/api/projects/{project}",
            f"/api/projects/{project}/schedule",
            f"/api/projects/{project}/versions",
            f"/api/projects/{project}/calculations/latest",
            f"/api/projects/{project}/planner",
            f"/api/projects/{project}/scenario/export",
        ):
            with self.subTest(viewer_read=path):
                self.assertEqual(viewer.get(path).status_code, 200)
        forbidden_viewer = (
            viewer.post(
                f"/api/projects/{project}/imports",
                files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "application/xml")},
            ),
            viewer.post(f"/api/projects/{project}/calculations"),
            viewer.post(
                f"/api/projects/{project}/scenario/reset",
                json={"expected_version_id": scenario["current_version_id"]},
            ),
            viewer.get(f"/api/projects/{project}/memberships"),
        )
        self.assertEqual([r.status_code for r in forbidden_viewer], [403] * 4)

        with self.connect() as conn:
            creator = conn.execute(
                "SELECT created_by_user_id FROM projects WHERE id=%s", (uuid.UUID(project),)
            ).fetchone()["created_by_user_id"]
            membership = conn.execute(
                "SELECT role FROM project_memberships WHERE project_id=%s AND user_id=%s",
                (uuid.UUID(project), user_a["id"]),
            ).fetchone()["role"]
        self.assertEqual(creator, user_a["id"])
        self.assertEqual(membership, "admin")

    def test_planner_can_mutate_but_cannot_administer_membership(self):
        admin, _, _, _ = self.authenticated("role-admin")
        planner, user, _, _ = self.authenticated("role-planner")
        project = admin.post("/api/projects", json={"name": "role-matrix"}).json()["id"]
        self.grant(admin, project, user, "planner")
        imported = planner.post(
            f"/api/projects/{project}/imports",
            files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "application/xml")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual(planner.post(f"/api/projects/{project}/calculations").status_code, 201)
        self.assertEqual(planner.get(f"/api/projects/{project}/memberships").status_code, 403)

    def test_membership_revocation_is_audited_and_cannot_remove_the_last_admin(self):
        admin, admin_user, _, _ = self.authenticated("membership-admin")
        member, member_user, _, _ = self.authenticated("membership-user")
        project = admin.post("/api/projects", json={"name": "membership-history"}).json()[
            "id"
        ]

        self.assertEqual(
            admin.post(
                f"/api/projects/{project}/memberships",
                json={"user_id": str(admin_user["id"]), "role": "viewer"},
            ).status_code,
            409,
        )
        self.assertEqual(
            admin.delete(
                f"/api/projects/{project}/memberships/{admin_user['id']}"
            ).status_code,
            409,
        )

        self.grant(admin, project, member_user, "viewer")
        self.grant(admin, project, member_user, "planner")
        issued = admin.post(
            f"/api/projects/{project}/device-tokens",
            json={"user_id": str(member_user["id"]), "role": "planner"},
        )
        self.assertEqual(issued.status_code, 201, issued.text)
        raw = issued.json()["raw_token"]

        revoked = admin.delete(
            f"/api/projects/{project}/memberships/{member_user['id']}"
        )
        self.assertEqual(revoked.status_code, 204, revoked.text)
        self.assertEqual(member.get(f"/api/projects/{project}").status_code, 404)
        device = self.app_client()
        device.headers["Authorization"] = f"Bearer {raw}"
        self.assertEqual(device.get(f"/api/projects/{project}").status_code, 401)

        with self.connect() as conn:
            events = conn.execute(
                """
                SELECT id, action, previous_role, role, actor_user_id
                FROM project_membership_events
                WHERE project_id=%s AND user_id=%s
                ORDER BY created_at, id
                """,
                (uuid.UUID(project), member_user["id"]),
            ).fetchall()
            token_revoked = conn.execute(
                "SELECT revoked_at FROM device_tokens WHERE token_hash=%s",
                (self.auth._token_hash(raw),),
            ).fetchone()["revoked_at"]
        self.assertEqual(
            [row["action"] for row in events],
            ["granted", "role_changed", "revoked"],
        )
        self.assertEqual(events[1]["previous_role"], "viewer")
        self.assertEqual(events[1]["role"], "planner")
        self.assertTrue(all(row["actor_user_id"] == admin_user["id"] for row in events))
        self.assertIsNotNone(token_revoked)

        with self.connect() as conn:
            with self.assertRaises(psycopg.errors.CheckViolation):
                conn.execute(
                    "UPDATE project_membership_events SET role='viewer' WHERE id=%s",
                    (events[0]["id"],),
                )
            conn.rollback()

    def test_sessions_expire_revoke_disable_and_persist_across_restart(self):
        from sto.persistence import auth_repositories as auth_repo

        client, row, secret, login = self.authenticated("session")
        project = client.post("/api/projects", json={"name": "restart-session"}).json()["id"]
        raw = client.cookies.get(self.auth.config.cookie_name)
        self.assertIsNotNone(raw)

        restarted = self.app_client()
        restarted.cookies.set(self.auth.config.cookie_name, raw)
        restarted.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        self.assertEqual(restarted.get(f"/api/projects/{project}").status_code, 200)
        actor = self.auth.authenticate_session(raw)
        self.auth.revoke_session(actor.session_id)
        self.assertEqual(restarted.get("/api/projects").status_code, 401)

        malformed = self.app_client()
        malformed.cookies.set(self.auth.config.cookie_name, "not-a-session-token")
        self.assertEqual(malformed.get("/api/projects").status_code, 401)

        self.advance()
        self.login(client, row, secret)
        replacement, replacement_user, _, _ = self.authenticated("session-replacement")
        self.grant(client, project, replacement_user, "admin")
        with self.connect() as conn:
            result = auth_repo.disable_user(conn, row["id"])
            conn.commit()
        self.assertTrue(result.changed)
        self.assertEqual(client.get("/api/projects").status_code, 401)

        expiring, _, _, _ = self.authenticated("expiring")
        self.advance(int(self.auth.config.session_ttl.total_seconds()) + 1)
        self.assertEqual(expiring.get("/api/projects").status_code, 401)

    def test_device_tokens_are_one_time_hashed_scoped_capped_and_revocable(self):
        from sto.persistence import auth_repositories as auth_repo

        admin, _, _, _ = self.authenticated("device-admin")
        target_client, target, _, _ = self.authenticated("device-user")
        first = admin.post("/api/projects", json={"name": "device-a"}).json()["id"]
        second = admin.post("/api/projects", json={"name": "device-b"}).json()["id"]
        self.grant(admin, first, target, "viewer")
        denied = admin.post(
            f"/api/projects/{first}/device-tokens",
            json={"user_id": str(target["id"]), "role": "planner"},
        )
        self.assertEqual(denied.status_code, 403)
        issued = admin.post(
            f"/api/projects/{first}/device-tokens",
            json={"user_id": str(target["id"]), "role": "viewer"},
        )
        self.assertEqual(issued.status_code, 201, issued.text)
        self.assertEqual(issued.headers["cache-control"], "private, no-store")
        body = issued.json()
        raw = body["raw_token"]
        self.assertTrue(raw.startswith("sto_dev_"))
        listed = admin.get(f"/api/projects/{first}/device-tokens").json()
        self.assertIsNone(listed[0]["raw_token"])
        with self.connect() as conn:
            stored = conn.execute(
                "SELECT token_hash, token_prefix FROM device_tokens WHERE id=%s",
                (uuid.UUID(body["id"]),),
            ).fetchone()
        self.assertNotEqual(stored["token_hash"], raw)
        self.assertNotIn(raw, str(stored))

        device = self.app_client()
        device.headers["Authorization"] = f"Bearer {raw}"
        device.headers.pop("X-CSRF-Token", None)
        self.assertEqual([row["id"] for row in device.get("/api/projects").json()], [first])
        self.assertEqual(device.get(f"/api/projects/{first}").status_code, 200)
        self.assertEqual(device.get(f"/api/projects/{second}").status_code, 404)
        self.assertEqual(device.post(f"/api/projects/{first}/calculations").status_code, 403)

        revoked = admin.delete(f"/api/projects/{first}/device-tokens/{body['id']}")
        self.assertEqual(revoked.status_code, 204, revoked.text)
        restarted = self.app_client()
        restarted.headers["Authorization"] = f"Bearer {raw}"
        self.assertEqual(restarted.get("/api/projects").status_code, 401)

        self.grant(admin, first, target, "planner")
        issued_again = admin.post(
            f"/api/projects/{first}/device-tokens",
            json={"user_id": str(target["id"]), "role": "planner"},
        ).json()["raw_token"]
        field_client = self.app_client()
        field_client.headers["Authorization"] = f"Bearer {issued_again}"
        field_client.headers.pop("X-CSRF-Token", None)
        imported = field_client.post(
            f"/api/projects/{first}/imports",
            files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "application/xml")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual(
            field_client.post(f"/api/projects/{first}/calculations").status_code,
            201,
        )
        with self.connect() as conn:
            auth_repo.disable_user(conn, target["id"])
            conn.commit()
        false_success = admin.post(
            f"/api/projects/{first}/device-tokens",
            json={"user_id": str(target["id"]), "role": "viewer"},
        )
        self.assertEqual(false_success.status_code, 403)
        self.assertEqual(field_client.get("/api/projects").status_code, 401)
        self.assertEqual(target_client.get("/api/projects").status_code, 401)

    def test_project_creation_and_admin_membership_are_atomic(self):
        from sto.persistence import auth_repositories as auth_repo

        client, _, _, _ = self.authenticated("atomic")
        before = client.get("/api/projects").json()
        with patch.object(auth_repo, "grant_membership", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                client.post("/api/projects", json={"name": "must-rollback"})
        self.assertEqual(client.get("/api/projects").json(), before)

    def test_project_and_cli_grants_control_a_concurrent_disable_refusal(self):
        from sto.cli.main import build_parser
        from sto.persistence import auth_repositories as auth_repo
        from sto.persistence import repositories as repo

        client, actor, _, _ = self.authenticated("grant-disable-race")
        before = client.get("/api/projects").json()
        with patch.object(
            auth_repo,
            "grant_membership",
            side_effect=auth_repo.DisabledUser("synthetic disable race"),
        ):
            refused = client.post("/api/projects", json={"name": "must-rollback"})
        self.assertEqual(refused.status_code, 401, refused.text)
        self.assertEqual(client.get("/api/projects").json(), before)

        with self.connect() as conn:
            project = repo.create_project(conn, name="grant-cli-race")
            conn.commit()
        args = build_parser().parse_args(
            ["auth", "grant-project", str(project["id"]), actor["username"], "viewer"]
        )
        with (
            patch("sto.persistence.db.connect", side_effect=self.connect),
            patch.object(
                auth_repo,
                "grant_membership",
                side_effect=auth_repo.DisabledUser("synthetic disable race"),
            ),
            self.assertRaises(SystemExit) as stopped,
        ):
            args.handler(args)
        self.assertEqual(str(stopped.exception), "no such enabled user")

    def test_disable_refuses_last_admin_and_serializes_with_demotion(self):
        from sto.persistence import auth_repositories as auth_repo

        admin_a, user_a, _, _ = self.authenticated("disable-admin-a")
        _, user_b, _, _ = self.authenticated("disable-admin-b")
        project = admin_a.post("/api/projects", json={"name": "disable-race"}).json()[
            "id"
        ]
        self.grant(admin_a, project, user_b, "admin")

        staged = threading.Event()
        disable_started = threading.Event()
        allow_commit = threading.Event()

        def demote_b():
            with self.connect() as conn:
                auth_repo.grant_membership(
                    conn,
                    project_id=uuid.UUID(project),
                    user_id=user_b["id"],
                    role="planner",
                    created_by_user_id=user_a["id"],
                )
                staged.set()
                self.assertTrue(allow_commit.wait(timeout=10))
                conn.commit()
            return "demoted"

        def disable_a():
            self.assertTrue(staged.wait(timeout=10))
            disable_started.set()
            with self.connect() as conn:
                try:
                    auth_repo.disable_user(conn, user_a["id"])
                    conn.commit()
                    return "disabled"
                except auth_repo.LastProjectAdministrator as error:
                    conn.rollback()
                    return str(error)

        with ThreadPoolExecutor(max_workers=2) as pool:
            demotion = pool.submit(demote_b)
            self.assertTrue(staged.wait(timeout=10))
            disabling = pool.submit(disable_a)
            self.assertTrue(disable_started.wait(timeout=10))
            allow_commit.set()
            self.assertEqual(demotion.result(timeout=10), "demoted")
            refusal = disabling.result(timeout=10)
        self.assertIn("grant another enabled administrator", refusal)

        with self.connect() as conn:
            enabled_admins = conn.execute(
                """
                SELECT count(*) AS count
                FROM project_memberships m JOIN users u ON u.id=m.user_id
                WHERE m.project_id=%s AND m.role='admin'
                  AND m.revoked_at IS NULL AND u.enabled
                """,
                (uuid.UUID(project),),
            ).fetchone()["count"]
        self.assertEqual(enabled_admins, 1)

    def test_disable_cli_reports_the_required_admin_action(self):
        from sto.cli.main import build_parser

        client, user, _, _ = self.authenticated("disable-cli")
        project = client.post("/api/projects", json={"name": "disable-cli"}).json()[
            "id"
        ]
        args = build_parser().parse_args(["auth", "disable-user", user["username"]])
        with (
            patch("sto.persistence.db.connect", side_effect=self.connect),
            self.assertRaises(SystemExit) as stopped,
        ):
            args.handler(args)
        self.assertIn("grant another enabled administrator", str(stopped.exception))
        self.assertEqual(client.get(f"/api/projects/{project}").status_code, 200)

    def test_accepted_disable_revokes_sessions_and_device_tokens(self):
        from sto.persistence import auth_repositories as auth_repo

        admin, user, _, _ = self.authenticated("disable-accepted")
        replacement, replacement_user, _, _ = self.authenticated("disable-replacement")
        project = admin.post("/api/projects", json={"name": "disable-accepted"}).json()[
            "id"
        ]
        self.grant(admin, project, replacement_user, "admin")
        issued = admin.post(
            f"/api/projects/{project}/device-tokens",
            json={"user_id": str(user["id"]), "role": "planner"},
        )
        self.assertEqual(issued.status_code, 201, issued.text)
        raw_device = issued.json()["raw_token"]

        with self.connect() as conn:
            result = auth_repo.disable_user(conn, user["id"])
            conn.commit()
        self.assertTrue(result.changed)
        self.assertGreaterEqual(result.sessions_revoked, 1)
        self.assertEqual(result.device_tokens_revoked, 1)
        self.assertEqual(admin.get("/api/projects").status_code, 401)
        device = self.app_client()
        device.headers["Authorization"] = f"Bearer {raw_device}"
        device.headers.pop("X-CSRF-Token", None)
        self.assertEqual(device.get("/api/projects").status_code, 401)
        self.assertEqual(replacement.get(f"/api/projects/{project}").status_code, 200)

    def test_scenario_reset_is_attributed_atomic_and_distinguishes_noop(self):
        from sto.persistence import repositories as repo

        client, actor, _, _ = self.authenticated("reset-audit")
        project, scenario = self.project_with_scenario(client, "reset-audit")
        baseline_id = scenario["baseline_version_id"]
        scenario_id = scenario["current_version_id"]

        stale = client.post(
            f"/api/projects/{project}/scenario/reset",
            json={"expected_version_id": str(uuid.uuid4())},
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        with self.connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) AS count FROM scenario_reset_events WHERE project_id=%s",
                    (uuid.UUID(project),),
                ).fetchone()["count"],
                0,
            )

        reset = client.post(
            f"/api/projects/{project}/scenario/reset",
            json={"expected_version_id": scenario_id},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertTrue(reset.json()["reset_performed"])
        event_id = uuid.UUID(reset.json()["reset_event_id"])
        self.assertEqual(reset.json()["current_version_id"], baseline_id)

        noop = client.post(
            f"/api/projects/{project}/scenario/reset",
            json={"expected_version_id": baseline_id},
        )
        self.assertEqual(noop.status_code, 200, noop.text)
        self.assertFalse(noop.json()["reset_performed"])
        self.assertIsNone(noop.json()["reset_event_id"])

        with self.connect() as conn:
            event = conn.execute(
                "SELECT * FROM scenario_reset_events WHERE id=%s", (event_id,)
            ).fetchone()
            self.assertEqual(event["project_id"], uuid.UUID(project))
            self.assertEqual(event["actor_user_id"], actor["id"])
            self.assertEqual(event["prior_scenario_version_id"], uuid.UUID(scenario_id))
            self.assertEqual(event["restored_baseline_version_id"], uuid.UUID(baseline_id))
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) AS count FROM scenario_reset_events WHERE project_id=%s",
                    (uuid.UUID(project),),
                ).fetchone()["count"],
                1,
            )
            with self.assertRaises(psycopg.errors.CheckViolation):
                conn.execute(
                    "UPDATE scenario_reset_events SET actor_user_id=%s WHERE id=%s",
                    (actor["id"], event_id),
                )
            conn.rollback()
        with self.connect() as conn:
            self.assertIsNotNone(
                repo.get_version(
                    conn, version_id=uuid.UUID(scenario_id), with_document=False
                )
            )

    def test_detailed_health_contains_both_database_failures(self):
        from sto.persistence import repositories as repo

        client, _, _, _ = self.authenticated("health-failure")
        client.post("/api/projects", json={"name": "health-private-project"})
        workspace = client.app.state.workspace
        with patch.object(
            repo,
            "list_projects_for_user",
            side_effect=RuntimeError("postgresql://secret-connection"),
        ):
            second_read = client.get("/api/health")
        self.assertEqual(second_read.status_code, 200, second_read.text)
        self.assertEqual(second_read.json()["status"], "degraded")
        self.assertEqual(second_read.json()["database"], "error: RuntimeError")
        self.assertEqual(second_read.json()["resident_projects"], 0)
        self.assertEqual(second_read.json()["integrity_failures"], {})
        self.assertNotIn("secret-connection", second_read.text)

        with patch.object(
            workspace,
            "connect",
            side_effect=RuntimeError("postgresql://another-secret"),
        ):
            first_read = client.get("/api/health")
            self.assertEqual(first_read.status_code, 200, first_read.text)
            self.assertEqual(first_read.json()["database"], "error: RuntimeError")
            self.assertNotIn("another-secret", first_read.text)
            anonymous = self.app_client()
            self.assertEqual(anonymous.get("/api/health").status_code, 401)
            self.assertEqual(anonymous.get("/healthz").json(), {"status": "ok"})

    def test_logout_revokes_the_persisted_session(self):
        from sto.persistence import auth_repositories as auth_repo

        client, _, _, _ = self.authenticated("logout")
        raw = client.cookies.get(self.auth.config.cookie_name)
        self.assertEqual(client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(client.get("/api/projects").status_code, 401)
        with self.connect() as conn:
            session = auth_repo.get_session_by_hash(conn, self.auth._token_hash(raw))
        self.assertIsNotNone(session["revoked_at"])

    def test_logout_403_and_500_do_not_revoke_or_claim_success(self):
        from fastapi.testclient import TestClient

        client, _, _, login = self.authenticated("logout-failures")
        raw = client.cookies.get(self.auth.config.cookie_name)
        refused = client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": "wrong-session-value"}
        )
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(client.get("/api/auth/session").status_code, 200)

        failure_client = TestClient(client.app, raise_server_exceptions=False)
        failure_client.__enter__()
        self.addCleanup(failure_client.__exit__, None, None, None)
        failure_client.cookies.set(self.auth.config.cookie_name, raw)
        failure_client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        with patch.object(
            self.auth, "revoke_session", side_effect=RuntimeError("synthetic outage")
        ):
            failed = failure_client.post("/api/auth/logout")
        self.assertEqual(failed.status_code, 500, failed.text)
        self.assertEqual(failure_client.get("/api/auth/session").status_code, 200)
        self.assertEqual(failure_client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(failure_client.get("/api/auth/session").status_code, 401)

    def test_login_after_unconfirmed_logout_atomically_revokes_the_old_session(self):
        client, row, secret, _ = self.authenticated("logout-login-rotation")
        old_raw = client.cookies.get(self.auth.config.cookie_name)
        self.assertIsNotNone(old_raw)

        refused = client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": "wrong-session-value"}
        )
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(client.get("/api/auth/session").status_code, 200)

        self.advance()
        replacement, _ = self.login(client, row, secret, advance=False)
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertNotEqual(client.cookies.get(self.auth.config.cookie_name), old_raw)

        old = self.app_client()
        old.cookies.set(self.auth.config.cookie_name, old_raw)
        self.assertEqual(old.get("/api/auth/session").status_code, 401)
        self.assertEqual(client.get("/api/auth/session").status_code, 200)


if __name__ == "__main__":
    unittest.main()
