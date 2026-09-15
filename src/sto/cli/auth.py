"""Bounded local administration for the PL2 authentication boundary."""

from __future__ import annotations

import argparse
import getpass
import uuid


def _service():
    # Authentication dependencies remain optional for canonical/core tooling.
    try:
        from sto.api.auth import AuthService
        from sto.persistence.db import connect
    except ImportError as error:
        raise SystemExit(
            f"authentication commands need the 'api' extra ({error.name} is missing): "
            "uv sync --extra api"
        ) from None
    return AuthService.from_environment(connect=connect)


def _password() -> str:
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("passwords do not match")
    try:
        from sto.api.auth import validate_password

        validate_password(first)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    return first


def _show_enrolment(row: dict, secret: str, uri: str) -> None:
    print(f"created user {row['username']} ({row['id']})")
    print("TOTP enrolment is shown once. Add it to the user's authenticator now.")
    print(f"secret: {secret}")
    print(f"otpauth URI: {uri}")


def _bootstrap_admin(args: argparse.Namespace) -> int:
    service = _service()
    try:
        from sto.api.auth import BootstrapClosed

        row, secret, uri = service.bootstrap_admin(
            username=args.username,
            password=_password(),
            display_name=args.display_name,
        )
    except BootstrapClosed as error:
        raise SystemExit(str(error)) from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
    _show_enrolment(row, secret, uri)
    print("No existing project access was granted. Use `sto auth grant-project` explicitly.")
    return 0


def _create_user(args: argparse.Namespace) -> int:
    try:
        row, secret, uri = _service().create_enrolled_user(
            username=args.username,
            password=_password(),
            display_name=args.display_name,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from None
    _show_enrolment(row, secret, uri)
    return 0


def _grant_project(args: argparse.Namespace) -> int:
    try:
        from sto.api.auth import normalize_username
        from sto.persistence import auth_repositories as auth_repo
        from sto.persistence import repositories as repo
        from sto.persistence.db import connect
    except ImportError as error:
        raise SystemExit(
            f"authentication commands need the 'api' extra ({error.name} is missing): "
            "uv sync --extra api"
        ) from None
    with connect() as conn:
        project = repo.get_project(conn, args.project_id)
        user = auth_repo.get_user_by_username(conn, normalize_username(args.username))
        if project is None:
            raise SystemExit("no such project")
        if user is None or not user["enabled"]:
            raise SystemExit("no such enabled user")
        membership = auth_repo.grant_membership(
            conn,
            project_id=args.project_id,
            user_id=user["id"],
            role=args.role,
            created_by_user_id=None,
        )
        conn.commit()
    print(
        f"granted {membership['role']} on {membership['project_id']} "
        f"to {user['username']} ({user['id']})"
    )
    return 0


def _disable_user(args: argparse.Namespace) -> int:
    try:
        from sto.api.auth import normalize_username
        from sto.persistence import auth_repositories as auth_repo
        from sto.persistence.db import connect
    except ImportError as error:
        raise SystemExit(
            f"authentication commands need the 'api' extra ({error.name} is missing): "
            "uv sync --extra api"
        ) from None
    with connect() as conn:
        user = auth_repo.get_user_by_username(conn, normalize_username(args.username))
        if user is None:
            raise SystemExit("no such user")
        try:
            result = auth_repo.disable_user(conn, user["id"])
        except auth_repo.LastProjectAdministrator as error:
            raise SystemExit(str(error)) from None
        conn.commit()
    print(
        f"user {user['username']} "
        f"{'disabled' if result.changed else 'was already disabled'}; "
        f"revoked {result.sessions_revoked} active session(s) and "
        f"{result.device_tokens_revoked} device token(s)"
    )
    return 0


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    auth = subparsers.add_parser(
        "auth", help="Bootstrap and boundedly administer local trial identities"
    )
    inner = auth.add_subparsers(dest="auth_command", required=True)

    bootstrap = inner.add_parser(
        "bootstrap-admin", help="Create the first user when the user table is empty"
    )
    bootstrap.add_argument("username")
    bootstrap.add_argument("--display-name")
    bootstrap.set_defaults(handler=_bootstrap_admin)

    create = inner.add_parser("create-user", help="Create another enrolled user")
    create.add_argument("username")
    create.add_argument("--display-name")
    create.set_defaults(handler=_create_user)

    grant = inner.add_parser("grant-project", help="Grant one project membership")
    grant.add_argument("project_id", type=uuid.UUID)
    grant.add_argument("username")
    grant.add_argument("role", choices=("viewer", "planner", "admin"))
    grant.set_defaults(handler=_grant_project)

    disable = inner.add_parser("disable-user", help="Disable a user and revoke sessions")
    disable.add_argument("username")
    disable.set_defaults(handler=_disable_user)
