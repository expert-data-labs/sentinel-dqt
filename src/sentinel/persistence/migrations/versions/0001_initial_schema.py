"""Initial schema: datasets, validation_runs, metrics, quality_events, incidents.

Revision ID: 0001
Revises:
Create Date: 2026-10-02
"""

from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE datasets (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            source_type      TEXT NOT NULL,
            environment      TEXT NOT NULL,
            owner            TEXT NOT NULL,
            criticality      TEXT NOT NULL
                CHECK (criticality IN ('low', 'medium', 'high', 'critical')),
            config_reference TEXT
        );
        CREATE INDEX ix_datasets_name ON datasets (name);

        CREATE TABLE validation_runs (
            id             UUID PRIMARY KEY,
            dataset_id     TEXT NOT NULL REFERENCES datasets (id),
            policy_version TEXT NOT NULL,
            started_at     TIMESTAMPTZ NOT NULL,
            finished_at    TIMESTAMPTZ NOT NULL,
            status         TEXT NOT NULL CHECK (status IN ('pass', 'warn', 'fail'))
        );
        -- Latest runs per dataset (history, dashboard health).
        CREATE INDEX ix_validation_runs_dataset_started
            ON validation_runs (dataset_id, started_at DESC);

        CREATE TABLE metrics (
            id                UUID PRIMARY KEY,
            validation_run_id UUID NOT NULL REFERENCES validation_runs (id) ON DELETE CASCADE,
            metric_name       TEXT NOT NULL,
            value             DOUBLE PRECISION NOT NULL,
            computed_at       TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX ix_metrics_run ON metrics (validation_run_id);
        -- Metric history lookups (adaptive thresholds, trends).
        CREATE INDEX ix_metrics_name_computed ON metrics (metric_name, computed_at DESC);

        CREATE TABLE quality_events (
            id                UUID PRIMARY KEY,
            validation_run_id UUID NOT NULL REFERENCES validation_runs (id) ON DELETE CASCADE,
            metric_id         UUID NOT NULL UNIQUE REFERENCES metrics (id) ON DELETE CASCADE,
            status            TEXT NOT NULL CHECK (status IN ('pass', 'warn', 'fail')),
            expected          TEXT NOT NULL,
            strategy_type     TEXT NOT NULL,
            severity          TEXT NOT NULL
                CHECK (severity IN ('info', 'warning', 'high', 'critical')),
            blocking          BOOLEAN NOT NULL,
            details           TEXT
        );
        CREATE INDEX ix_quality_events_run ON quality_events (validation_run_id);

        CREATE TABLE incidents (
            id                UUID PRIMARY KEY,
            validation_run_id UUID NOT NULL REFERENCES validation_runs (id) ON DELETE CASCADE,
            quality_event_id  UUID NOT NULL UNIQUE
                REFERENCES quality_events (id) ON DELETE CASCADE,
            priority          TEXT NOT NULL
                CHECK (priority IN ('info', 'warning', 'high', 'critical')),
            score             DOUBLE PRECISION NOT NULL,
            components        TEXT NOT NULL,
            reasons           TEXT NOT NULL
        );
        CREATE INDEX ix_incidents_run ON incidents (validation_run_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE incidents;
        DROP TABLE quality_events;
        DROP TABLE metrics;
        DROP TABLE validation_runs;
        DROP TABLE datasets;
        """
    )
