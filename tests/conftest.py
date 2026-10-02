"""Shared fixtures for tests that need Sentinel's Postgres store.

A ``sentinel_test`` database is recreated once per test session on the server
from SENTINEL_TEST_POSTGRES_DSN (default: the docker compose Postgres) and
migrated to head. Each test gets a connection with every table emptied first.

Without a reachable Postgres these tests are skipped, unless
SENTINEL_REQUIRE_POSTGRES=1 (set in CI), where they fail instead.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql

from sentinel.persistence import migrate
from sentinel.persistence.engine import StoreConnection, connect

_DEFAULT_DSN = "postgresql://sentinel:sentinel@localhost:5432/sentinel"
_TEST_DATABASE = "sentinel_test"
_TABLES = "incidents, quality_events, metrics, validation_runs, datasets"


def _with_database(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


@pytest.fixture(scope="session")
def store_url() -> str:
    """URL of a freshly created and migrated test database."""
    server_dsn = os.environ.get("SENTINEL_TEST_POSTGRES_DSN", _DEFAULT_DSN)
    try:
        admin = psycopg.connect(_with_database(server_dsn, "postgres"), autocommit=True)
    except psycopg.OperationalError as exc:
        message = f"Postgres not reachable ({exc}); start it with `docker compose up -d`"
        if os.environ.get("SENTINEL_REQUIRE_POSTGRES") == "1":
            pytest.fail(message)
        pytest.skip(message)

    with admin:
        name = sql.Identifier(_TEST_DATABASE)
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(name))

    url = _with_database(server_dsn, _TEST_DATABASE)
    migrate.upgrade(url)
    return url


@pytest.fixture
def store(store_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[StoreConnection]:
    """A connection to the empty test store. Also points SENTINEL_DATABASE_URL at it."""
    monkeypatch.setenv("SENTINEL_DATABASE_URL", store_url)
    conn = connect(store_url)
    conn.execute(f"TRUNCATE {_TABLES} CASCADE")
    try:
        yield conn
    finally:
        conn.close()
