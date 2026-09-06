"""Idempotent schema creation for the persistence store.

Four tables (docs/architecture/0003-milestone-2-architecture.md Part 4),
matching the ValidationRun/Metric/QualityEvent composition already in the
domain model rather than inventing new normalization. No Alembic yet —
that's the planned SQLAlchemy + PostgreSQL home for real migrations; for
four tables with no migration history to manage, CREATE TABLE IF NOT
EXISTS run once per connection is the plainest thing that works.

``datasets.id`` reuses the domain Dataset.id (a human-assigned string,
FR-01) as its own primary key. The other three tables get UUID surrogate
keys, generated in Python at mapping time (sentinel.persistence.mapping),
not left to a DB-side default. Timestamps are TIMESTAMPTZ, not TIMESTAMP:
every datetime this codebase produces (ValidationRun.started_at/
finished_at, Metric.computed_at) is timezone-aware UTC, and a plain
TIMESTAMP column would silently discard that.
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
)


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the persistence store's tables if they don't already exist.

    Safe to call on every CLI invocation (and more than once per test) —
    each statement is CREATE TABLE IF NOT EXISTS, applied in dependency
    order (datasets before validation_runs before metrics before
    quality_events) so the foreign keys always resolve.
    """
    for statement in _STATEMENTS:
        conn.execute(statement)
