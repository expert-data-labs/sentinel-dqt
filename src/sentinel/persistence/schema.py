"""Creates the store's tables if they don't exist.

Tables: datasets, validation_runs, metrics, quality_events, incidents.
``datasets.id`` is the Dataset's own id; other tables use UUIDs generated in
Python. Timestamps are TIMESTAMPTZ (all datetimes are UTC-aware). No migration
framework: columns added later use ``ADD COLUMN IF NOT EXISTS``.
"""

from __future__ import annotations

import duckdb

_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS datasets (
        id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        source_type VARCHAR NOT NULL,
        environment VARCHAR NOT NULL,
        owner VARCHAR NOT NULL,
        criticality VARCHAR NOT NULL,
        config_reference VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS validation_runs (
        id UUID PRIMARY KEY,
        dataset_id VARCHAR NOT NULL REFERENCES datasets(id),
        policy_version VARCHAR NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ NOT NULL,
        status VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metrics (
        id UUID PRIMARY KEY,
        validation_run_id UUID NOT NULL REFERENCES validation_runs(id),
        metric_name VARCHAR NOT NULL,
        value DOUBLE NOT NULL,
        computed_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quality_events (
        id UUID PRIMARY KEY,
        validation_run_id UUID NOT NULL REFERENCES validation_runs(id),
        metric_id UUID NOT NULL REFERENCES metrics(id),
        status VARCHAR NOT NULL,
        expected VARCHAR NOT NULL,
        strategy_type VARCHAR NOT NULL,
        severity VARCHAR NOT NULL,
        blocking BOOLEAN NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS incidents (
        id UUID PRIMARY KEY,
        validation_run_id UUID NOT NULL REFERENCES validation_runs(id),
        quality_event_id UUID NOT NULL REFERENCES quality_events(id),
        priority VARCHAR NOT NULL,
        score DOUBLE NOT NULL,
        components VARCHAR NOT NULL,
        reasons VARCHAR NOT NULL
    )
    """,
)

# Columns added after a table first shipped. CREATE TABLE IF NOT EXISTS
# won't add them to an existing table, so they need their own statements.
_COLUMN_ADDITIONS: tuple[str, ...] = (
    "ALTER TABLE quality_events ADD COLUMN IF NOT EXISTS details VARCHAR",
)


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create tables, then add later columns. Idempotent.

    Tables are created in foreign-key order.
    """
    for statement in _STATEMENTS:
        conn.execute(statement)
    for statement in _COLUMN_ADDITIONS:
        conn.execute(statement)
