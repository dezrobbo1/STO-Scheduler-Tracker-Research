"""Connections. One URL from the environment, one place that reads it."""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

#: The deployment's PostgreSQL listens on loopback 5433 (no Docker on the host);
#: ``localhost`` resolves to ``::1`` there and is refused, so the address is
#: spelled out.
DEFAULT_DATABASE_URL = "postgresql://postgres@127.0.0.1:5433/sto"


def database_url() -> str:
    return os.environ.get("STO_DATABASE_URL", DEFAULT_DATABASE_URL)


def connect(url: str | None = None) -> psycopg.Connection:
    """A connection with dict rows. Callers own the transaction."""

    return psycopg.connect(url or database_url(), row_factory=dict_row)
