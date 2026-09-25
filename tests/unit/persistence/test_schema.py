from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from sentinel.persistence.engine import get_connection
from sentinel.persistence.schema import ensure_schema


def _table_names(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def test_ensure_schema_creates_all_five_tables(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.duckdb")

    ensure_schema(conn)

    assert _table_names(conn) == {
        "datasets",
        "validation_runs",
        "metrics",
        "quality_events",
        "incidents",
    }


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.duckdb")

    ensure_schema(conn)
    ensure_schema(conn)  # must not raise on the second call

    assert _table_names(conn) == {
        "datasets",
        "validation_runs",
        "metrics",
        "quality_events",
        "incidents",
    }


def test_foreign_keys_are_enforced_in_dependency_order(tmp_path: Path) -> None:
    """A row inserted out of dependency order (a validation_run referencing
    a dataset that doesn't exist) should fail — proves the tables were
    actually created with the FK relationships intact, not just as bare
    unconstrained tables."""
    conn = get_connection(tmp_path / "test.duckdb")
    ensure_schema(conn)

    with pytest.raises(duckdb.Error):
        conn.execute(
            "INSERT INTO validation_runs "
            "(id, dataset_id, policy_version, started_at, finished_at, status) "
            "VALUES (gen_random_uuid(), 'does_not_exist', 'v1', now(), now(), 'pass')"
        )


def _column_names(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ?",
        [table],
    ).fetchall()
    return {row[0] for row in rows}


def test_incidents_table_has_the_expected_columns(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.duckdb")
    ensure_schema(conn)

    assert _column_names(conn, "incidents") == {
        "id",
        "validation_run_id",
        "quality_event_id",
        "priority",
        "score",
        "components",
        "reasons",
    }


def test_quality_events_gains_a_details_column(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.duckdb")
    ensure_schema(conn)

    assert "details" in _column_names(conn, "quality_events")


def test_ensure_schema_adds_the_details_column_to_a_pre_migration_database(
    tmp_path: Path,
) -> None:
    """The real-world case this migration has to handle: a sentinel.duckdb
    file created by an earlier Milestone (0-5), before ``incidents`` or
    ``quality_events.details`` existed. ``CREATE TABLE IF NOT EXISTS``
    alone would leave such a database's quality_events table exactly as
    it was -- this proves the separate ALTER TABLE pass actually adds the
    missing column to a table that already exists, not just to a
    freshly-created one."""
    conn = get_connection(tmp_path / "test.duckdb")
    # Simulates the pre-Milestone-6 schema directly, without importing
    # schema.py's own (now-updated) statements -- this table shape is
    # frozen in time on purpose, to represent "what M0-M5 already wrote
    # to disk", not "whatever schema.py currently says".
    conn.execute(
        """
        CREATE TABLE quality_events (
            id UUID PRIMARY KEY,
            validation_run_id UUID NOT NULL,
            metric_id UUID NOT NULL,
            status VARCHAR NOT NULL,
            expected VARCHAR NOT NULL,
            strategy_type VARCHAR NOT NULL,
            severity VARCHAR NOT NULL,
            blocking BOOLEAN NOT NULL
        )
        """
    )
    assert "details" not in _column_names(conn, "quality_events")

    ensure_schema(conn)

    assert "details" in _column_names(conn, "quality_events")
