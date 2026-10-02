"""Connections to Sentinel's Postgres store.

The URL comes from ``SENTINEL_DATABASE_URL`` (default: the docker compose
database). Connections use autocommit; writes open explicit transactions.
Sessions run in UTC so returned timestamps are consistent.
"""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool

DATABASE_URL_ENV = "SENTINEL_DATABASE_URL"
DEFAULT_DATABASE_URL = "postgresql://sentinel:sentinel@localhost:5432/sentinel"

StoreConnection = psycopg.Connection[TupleRow]

_CONNECT_KWARGS: dict[str, object] = {"autocommit": True, "options": "-c timezone=UTC"}


def database_url(url: str | None = None) -> str:
    """Resolve the store URL: ``url`` argument, then the env var, then the default."""
    return url or os.environ.get(DATABASE_URL_ENV) or DEFAULT_DATABASE_URL


def connect(url: str | None = None) -> StoreConnection:
    """Open one connection (for the CLI and scripts)."""
    return psycopg.connect(database_url(url), **_CONNECT_KWARGS)  # type: ignore[arg-type]


def create_pool(
    url: str | None = None, *, min_size: int = 1, max_size: int = 10
) -> ConnectionPool[StoreConnection]:
    """Open a connection pool for concurrent callers (dashboard, API workers)."""
    return ConnectionPool(
        database_url(url),
        min_size=min_size,
        max_size=max_size,
        kwargs=_CONNECT_KWARGS,
        open=True,
    )
