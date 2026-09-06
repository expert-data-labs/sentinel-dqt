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


def test_ensure_schema_creates_all_four_tables(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.duckdb")

    ensure_schema(conn)

    assert _table_names(conn) == {"datasets", "validation_runs", "metrics", "quality_events"}


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "test.duckdb")

    ensure_schema(conn)
    ensure_schema(conn)  # must not raise on the second call

    assert _table_names(conn) == {"datasets", "validation_runs", "metrics", "quality_events"}


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
