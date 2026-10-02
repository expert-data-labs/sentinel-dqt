"""The Alembic migrations against the Postgres test store."""

from __future__ import annotations

import psycopg
import pytest

from sentinel.persistence import migrate
from sentinel.persistence.engine import StoreConnection, connect

_TABLES = {"datasets", "validation_runs", "metrics", "quality_events", "incidents"}


def _table_names(conn: StoreConnection) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    return {row[0] for row in rows} - {"alembic_version"}


def _column_names(conn: StoreConnection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchall()
    return {row[0] for row in rows}


def test_upgrade_creates_all_five_tables(store: StoreConnection) -> None:
    assert _table_names(store) == _TABLES


def test_store_is_at_the_head_revision(store: StoreConnection) -> None:
    assert migrate.current_revision(store) == migrate.head_revision()


def test_upgrade_is_idempotent(store_url: str, store: StoreConnection) -> None:
    migrate.upgrade(store_url)  # already at head: no-op
    assert _table_names(store) == _TABLES


def test_downgrade_then_upgrade_round_trips(store_url: str) -> None:
    migrate.downgrade(store_url)
    with connect(store_url) as conn:
        assert _table_names(conn) == set()
        assert migrate.current_revision(conn) is None

    migrate.upgrade(store_url)
    with connect(store_url) as conn:
        assert _table_names(conn) == _TABLES


def test_incidents_and_quality_events_have_the_expected_columns(store: StoreConnection) -> None:
    assert _column_names(store, "incidents") == {
        "id",
        "validation_run_id",
        "quality_event_id",
        "priority",
        "score",
        "components",
        "reasons",
    }
    assert "details" in _column_names(store, "quality_events")


def test_foreign_keys_are_enforced(store: StoreConnection) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        store.execute(
            "INSERT INTO validation_runs "
            "(id, dataset_id, policy_version, started_at, finished_at, status) "
            "VALUES (gen_random_uuid(), 'does_not_exist', 'v1', now(), now(), 'pass')"
        )


def test_status_values_are_checked(store: StoreConnection) -> None:
    store.execute(
        "INSERT INTO datasets (id, name, source_type, environment, owner, criticality) "
        "VALUES ('d', 'd', 'duckdb', 'test', 'team', 'low')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        store.execute(
            "INSERT INTO validation_runs "
            "(id, dataset_id, policy_version, started_at, finished_at, status) "
            "VALUES (gen_random_uuid(), 'd', 'v1', now(), now(), 'unknown')"
        )
