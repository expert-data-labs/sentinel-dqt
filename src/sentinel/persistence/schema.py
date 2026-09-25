"""Idempotent schema creation for the persistence store.

Four tables (docs/architecture/0003-milestone-2-architecture.md Part 4),
matching the ValidationRun/Metric/QualityEvent composition already in the
domain model rather than inventing new normalization. No Alembic yet --
that's the planned SQLAlchemy + PostgreSQL home for real migrations; for
four tables with no migration history to manage, CREATE TABLE IF NOT
EXISTS run once per connection is the plainest thing that works.

``datasets.id`` reuses the domain Dataset.id (a human-assigned string,
FR-01) as its own primary key. The other tables get UUID surrogate keys,
generated in Python at mapping time (sentinel.persistence.mapping), not
left to a DB-side default. Timestamps are TIMESTAMPTZ, not TIMESTAMP:
every datetime this codebase produces (ValidationRun.started_at/
finished_at, Metric.computed_at) is timezone-aware UTC, and a plain
TIMESTAMP column would silently discard that.

Milestone 6 (Observability) adds a fifth table, ``incidents`` -- one row
per Incident, the same "additive, not a rewrite" growth every prior
milestone's schema change has been -- plus one new column,
``quality_events.details``. Both close a gap Milestone 5 explicitly
deferred rather than solved (see docs/architecture/0007-milestone-6-
design.md Part 3): ``ValidationRun.incidents`` and
``ThresholdResult.details`` were already being computed in memory, just
never written down. Nothing about the four original tables changes
shape or meaning.

``ensure_schema`` runs two passes: the existing ``CREATE TABLE IF NOT
EXISTS`` statements (a no-op against a database that already has these
tables -- crucially, that includes not adding a column to a table that
already exists), and then a second pass of ``ALTER TABLE ... ADD COLUMN
IF NOT EXISTS`` statements for columns added to an existing table after
that table first shipped. DuckDB supports ``IF NOT EXISTS`` on
``ADD COLUMN`` directly, which is the smallest mechanism that keeps
``ensure_schema`` safe to call against both a brand-new store and one
created by an earlier milestone -- no real migration framework, same
restraint as the rest of this file.
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

# Milestone 6: columns added to a table that shipped in an earlier
# milestone. Kept separate from _STATEMENTS above because
# "CREATE TABLE IF NOT EXISTS" and "ALTER TABLE ... ADD COLUMN IF NOT
# EXISTS" are different idempotency mechanisms -- the former no-ops
# against an existing table without inspecting its columns at all, so a
# column added after a table's original CREATE TABLE statement needs
# its own, separate, idempotent statement to reach a store created
# before this migration existed.
_COLUMN_ADDITIONS: tuple[str, ...] = (
    "ALTER TABLE quality_events ADD COLUMN IF NOT EXISTS details VARCHAR",
)


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the persistence store's tables (and add any columns a
    later milestone introduced to an earlier table) if they don't
    already exist.

    Safe to call on every CLI invocation (and more than once per test) --
    every statement here is idempotent, applied in dependency order
    (datasets before validation_runs before metrics before quality_events
    before incidents) so foreign keys always resolve, with column
    additions applied last since they depend on their table already
    existing.
    """
    for statement in _STATEMENTS:
        conn.execute(statement)
    for statement in _COLUMN_ADDITIONS:
        conn.execute(statement)
