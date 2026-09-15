"""Password, TOTP, session and device-token security at the API edge."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pyotp
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from sto.persistence import auth_repositories as auth_repo

ROLE_LEVEL = {"viewer": 1, "planner": 2, "admin": 3}
SESSION_COOKIE = "sto_session"


class AuthenticationFailed(Exception):
    """A deliberately generic credential failure."""


class AuthenticationConfigurationError(RuntimeError):
    """Authentication cannot start securely with the supplied configuration."""


class BootstrapClosed(Exception):
    """The first-user-only bootstrap has already been used."""


class AuthorizationFailed(Exception):
    """An authenticated actor cannot perform the requested operation."""


@dataclass(frozen=True)
class AuthConfig:
    master_key: bytes
    session_ttl: timedelta = timedelta(hours=8)
    cookie_secure: bool = False
    cookie_name: str = SESSION_COOKIE
    totp_window: int = 1

    @classmethod
    def from_environment(cls) -> AuthConfig:
        raw = os.environ.get("STO_AUTH_MASTER_KEY")
        if not raw:
            raise AuthenticationConfigurationError(
                "STO_AUTH_MASTER_KEY is required; generate a Fernet key and supply it "
                "outside git"
            )
        try:
            key = raw.encode("ascii", errors="strict")
            Fernet(key)
        except (UnicodeEncodeError, ValueError, TypeError) as error:
            raise AuthenticationConfigurationError(
                "STO_AUTH_MASTER_KEY must be one URL-safe base64-encoded 32-byte Fernet key"
            ) from error

        raw_ttl = os.environ.get("STO_SESSION_TTL_SECONDS", str(8 * 60 * 60))
        try:
            ttl_seconds = int(raw_ttl)
        except ValueError as error:
            raise AuthenticationConfigurationError(
                "STO_SESSION_TTL_SECONDS must be an integer"
            ) from error
        if not 300 <= ttl_seconds <= 7 * 24 * 60 * 60:
            raise AuthenticationConfigurationError(
                "STO_SESSION_TTL_SECONDS must be between 300 and 604800"
            )
        secure_value = os.environ.get("STO_COOKIE_SECURE", "0").strip().lower()
        if secure_value not in {"0", "1", "false", "true"}:
            raise AuthenticationConfigurationError(
                "STO_COOKIE_SECURE must be 0/1 or false/true"
            )
        return cls(
            master_key=key,
            session_ttl=timedelta(seconds=ttl_seconds),
            cookie_secure=secure_value in {"1", "true"},
        )


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    username: str
    display_name: str | None
    authentication: Literal["browser", "device"]
    session_id: uuid.UUID | None = None
    device_token_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    role_cap: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "authentication": self.authentication,
        }


@dataclass(frozen=True)
class ProjectAccess:
    actor: Actor
    project_id: uuid.UUID
    role: str


@dataclass(frozen=True)
class LoginResult:
    actor: Actor
    raw_session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class DeviceTokenResult:
    row: dict[str, Any]
    raw_token: str


def normalize_username(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def role_allows(actual: str, required: str) -> bool:
    return ROLE_LEVEL.get(actual, 0) >= ROLE_LEVEL[required]


def lesser_role(first: str, second: str) -> str:
    return first if ROLE_LEVEL[first] <= ROLE_LEVEL[second] else second


class AuthService:
    """One security boundary over a caller-supplied PostgreSQL connection."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        config: AuthConfig,
        password_hasher: PasswordHasher | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.connect = connect
        self.config = config
        self.password_hasher = password_hasher or PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._fernet = Fernet(config.master_key)
        master = base64.urlsafe_b64decode(config.master_key)
        self._token_pepper = hmac.new(
            master, b"sto-token-hash-v1", hashlib.sha256
        ).digest()
        self._csrf_pepper = hmac.new(
            master, b"sto-session-csrf-v1", hashlib.sha256
        ).digest()
        self._now = now or (lambda: datetime.now(UTC))
        # A missing username still pays an Argon2 verification cost and gets
        # the same response as every other bad credential combination.
        self._dummy_hash = self.password_hasher.hash(secrets.token_urlsafe(24))

    @classmethod
    def from_environment(cls, *, connect: Callable[[], Any]) -> AuthService:
        return cls(connect=connect, config=AuthConfig.from_environment())

    @classmethod
    def for_tests(
        cls,
        *,
        connect: Callable[[], Any],
        now: Callable[[], datetime] | None = None,
        session_ttl: timedelta = timedelta(hours=8),
    ) -> AuthService:
        return cls(
            connect=connect,
            config=AuthConfig(master_key=Fernet.generate_key(), session_ttl=session_ttl),
            password_hasher=PasswordHasher(
                time_cost=1,
                memory_cost=8192,
                parallelism=1,
                hash_len=16,
                salt_len=16,
                type=Type.ID,
            ),
            now=now,
        )

    def _token_hash(self, raw: str) -> str:
        return hmac.new(
            self._token_pepper, raw.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def now(self) -> datetime:
        return self._now()

    def csrf_token(self, raw_session_token: str) -> str:
        digest = hmac.new(
            self._csrf_pepper,
            b"csrf\0" + raw_session_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def valid_csrf(self, raw_session_token: str, supplied: str | None) -> bool:
        return supplied is not None and secrets.compare_digest(
            self.csrf_token(raw_session_token), supplied
        )

    def encrypt_totp_secret(self, secret: str) -> bytes:
        return self._fernet.encrypt(secret.encode("ascii"))

    def decrypt_totp_secret(self, encrypted: bytes) -> str:
        try:
            return self._fernet.decrypt(bytes(encrypted)).decode("ascii")
        except (InvalidToken, UnicodeDecodeError) as error:
            raise AuthenticationFailed from error

    def create_user(
        self,
        *,
        username: str,
        password: str,
        totp_secret: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_username(username)
        if not normalized:
            raise ValueError("username must not be blank")
        if len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        pyotp.TOTP(totp_secret, digits=6, interval=30)
        password_hash = self.password_hasher.hash(password)
        encrypted_secret = self.encrypt_totp_secret(totp_secret)
        with self.connect() as conn:
            row = auth_repo.insert_user(
                conn,
                username=username.strip(),
                normalized_username=normalized,
                display_name=None if display_name is None else display_name.strip() or None,
                password_hash=password_hash,
                totp_secret_encrypted=encrypted_secret,
            )
            conn.commit()
        return row

    def create_enrolled_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
    ) -> tuple[dict[str, Any], str, str]:
        secret = pyotp.random_base32(length=32)
        row = self.create_user(
            username=username,
            password=password,
            totp_secret=secret,
            display_name=display_name,
        )
        uri = pyotp.TOTP(secret, digits=6, interval=30).provisioning_uri(
            name=row["username"], issuer_name="STO Scheduler + Tracker"
        )
        return row, secret, uri

    def bootstrap_admin(
        self, *, username: str, password: str, display_name: str | None = None
    ) -> tuple[dict[str, Any], str, str]:
        secret = pyotp.random_base32(length=32)
        normalized = normalize_username(username)
        if not normalized:
            raise ValueError("username must not be blank")
        if len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        password_hash = self.password_hasher.hash(password)
        encrypted_secret = self.encrypt_totp_secret(secret)
        with self.connect() as conn:
            auth_repo.lock_bootstrap(conn)
            if auth_repo.count_users(conn) != 0:
                raise BootstrapClosed("authentication bootstrap is already complete")
            row = auth_repo.insert_user(
                conn,
                username=username.strip(),
                normalized_username=normalized,
                display_name=None if display_name is None else display_name.strip() or None,
                password_hash=password_hash,
                totp_secret_encrypted=encrypted_secret,
            )
            conn.commit()
        uri = pyotp.TOTP(secret, digits=6, interval=30).provisioning_uri(
            name=row["username"], issuer_name="STO Scheduler + Tracker"
        )
        return row, secret, uri

    @staticmethod
    def _matching_totp_counter(secret: str, otp: str, now: datetime, window: int) -> int | None:
        if len(otp) != 6 or not otp.isdigit():
            return None
        totp = pyotp.TOTP(secret, digits=6, interval=30)
        current = int(now.timestamp()) // totp.interval
        for counter in range(current + window, current - window - 1, -1):
            if secrets.compare_digest(totp.at(counter * totp.interval), otp):
                return counter
        return None

    def login(self, *, username: str, password: str, otp: str) -> LoginResult:
        now = self._now()
        normalized = normalize_username(username)
        with self.connect() as conn:
            user = auth_repo.get_user_by_username(conn, normalized)

        # Argon2 and TOTP verification are deliberately outside a transaction
        # lock. Only the replay-counter compare/update below is serialized.
        candidate_hash = self._dummy_hash if user is None else user["password_hash"]
        try:
            password_ok = self.password_hasher.verify(candidate_hash, password)
        except (VerificationError, InvalidHashError):
            password_ok = False

        counter = None
        if user is not None and user["enabled"] and password_ok:
            secret = self.decrypt_totp_secret(user["totp_secret_encrypted"])
            counter = self._matching_totp_counter(
                secret, otp.strip(), now, self.config.totp_window
            )
        if user is None or not user["enabled"] or not password_ok or counter is None:
            raise AuthenticationFailed

        replacement = (
            self.password_hasher.hash(password)
            if self.password_hasher.check_needs_rehash(user["password_hash"])
            else None
        )
        with self.connect() as conn:
            locked = auth_repo.get_user_by_username(conn, normalized, for_update=True)
            if (
                locked is None
                or locked["id"] != user["id"]
                or not locked["enabled"]
                or (
                    locked["last_totp_counter"] is not None
                    and counter <= locked["last_totp_counter"]
                )
            ):
                raise AuthenticationFailed
            auth_repo.record_login(
                conn, user_id=user["id"], totp_counter=counter, password_hash=replacement
            )
            raw, prefix = self._new_token("sto_s")
            expires = now + self.config.session_ttl
            session = auth_repo.insert_session(
                conn,
                user_id=user["id"],
                token_hash=self._token_hash(raw),
                token_prefix=prefix,
                expires_at=expires,
            )
            conn.commit()
        actor = Actor(
            user_id=user["id"],
            username=user["username"],
            display_name=user["display_name"],
            authentication="browser",
            session_id=session["id"],
        )
        return LoginResult(actor, raw, self.csrf_token(raw), expires)

    @staticmethod
    def _new_token(kind: str) -> tuple[str, str]:
        secret = secrets.token_urlsafe(32)
        # The display prefix is random independently of the bearer secret, so
        # listing/revocation screens do not reveal even a fragment of it.
        prefix = f"{kind}_{secrets.token_urlsafe(6)[:8]}"
        return f"{prefix}.{secret}", prefix

    def authenticate_session(self, raw: str) -> Actor:
        with self.connect() as conn:
            row = auth_repo.get_session_by_hash(conn, self._token_hash(raw))
        now = self._now()
        if (
            row is None
            or row["revoked_at"] is not None
            or not row["enabled"]
            or row["expires_at"] <= now
        ):
            raise AuthenticationFailed
        return Actor(
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            authentication="browser",
            session_id=row["id"],
        )

    def authenticate_device(self, raw: str) -> Actor:
        with self.connect() as conn:
            row = auth_repo.get_device_token_by_hash(conn, self._token_hash(raw))
        now = self._now()
        if (
            row is None
            or row["revoked_at"] is not None
            or not row["enabled"]
            or (row["expires_at"] is not None and row["expires_at"] <= now)
        ):
            raise AuthenticationFailed
        return Actor(
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            authentication="device",
            device_token_id=row["id"],
            project_id=row["project_id"],
            role_cap=lesser_role(row["token_role"], row["membership_role"]),
        )

    def revoke_session(self, session_id: uuid.UUID) -> None:
        with self.connect() as conn:
            auth_repo.revoke_session(conn, session_id)
            conn.commit()

    def issue_device_token(
        self,
        *,
        issuer: Actor,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        expires_at: datetime | None,
    ) -> DeviceTokenResult:
        if role not in {"viewer", "planner"}:
            raise ValueError("device tokens are limited to viewer or planner")
        with self.connect() as conn:
            target = auth_repo.get_user(conn, user_id, for_update=True)
            issuer_membership = auth_repo.get_membership(
                conn, project_id=project_id, user_id=issuer.user_id
            )
            target_membership = auth_repo.get_membership(
                conn, project_id=project_id, user_id=user_id
            )
            if (
                issuer_membership is None
                or not role_allows(issuer_membership["role"], "admin")
                or target is None
                or not target["enabled"]
                or target_membership is None
                or not role_allows(issuer_membership["role"], role)
                or not role_allows(target_membership["role"], role)
            ):
                raise AuthorizationFailed
            raw, prefix = self._new_token("sto_dev")
            row = auth_repo.insert_device_token(
                conn,
                user_id=user_id,
                project_id=project_id,
                role=role,
                token_hash=self._token_hash(raw),
                token_prefix=prefix,
                expires_at=expires_at,
                issued_by_user_id=issuer.user_id,
            )
            conn.commit()
        return DeviceTokenResult(row=row, raw_token=raw)
