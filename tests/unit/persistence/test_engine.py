from __future__ import annotations

from datetime import datetime

import pytest

from sentinel.persistence.engine import (
    DATABASE_URL_ENV,
    DEFAULT_DATABASE_URL,
    StoreConnection,
    connect,
    create_pool,
    database_url,
)


def test_database_url_prefers_the_explicit_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql://env/db")
    assert database_url("postgresql://arg/db") == "postgresql://arg/db"


def test_database_url_falls_back_to_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql://env/db")
    assert database_url() == "postgresql://env/db"


def test_database_url_defaults_to_the_compose_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert database_url() == DEFAULT_DATABASE_URL


def test_connections_use_autocommit_and_utc(store_url: str) -> None:
    with connect(store_url) as conn:
        assert conn.autocommit
        row = conn.execute("SELECT now()").fetchone()
        assert row is not None
        now: datetime = row[0]
        assert now.utcoffset() is not None and now.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_pool_hands_out_working_connections(store_url: str) -> None:
    with create_pool(store_url, min_size=1, max_size=2) as pool:
        with pool.connection() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)


def test_store_fixture_gives_an_empty_store(store: StoreConnection) -> None:
    assert store.execute("SELECT count(*) FROM validation_runs").fetchone() == (0,)
