"""Writes a fully-mapped validation run to the persistence store.

One function, shaped around exactly what ``sentinel validate`` needs --
see docs/architecture/0003-milestone-2-architecture.md Part 6 for why
this is a narrow function rather than a generic repository.

Milestone 6 adds one more insert loop, ``incidents``, in the same
transaction as everything else -- an Incident is only ever meaningful
alongside the ValidationRun and QualityEvent that produced it, so it's
never persisted independently of them. ``quality_events.details`` (also
Milestone 6) is written as part of the existing quality_events insert,
not a separate statement.
"""

from __future__ import annotations

import uuid

import duckdb

from sentinel.domain import ValidationRun
from sentinel.persistence.mapping import to_rows


def persist_validation_run(conn: duckdb.DuckDBPyConnection, run: ValidationRun) -> uuid.UUID:
    """Persist the run's dataset, the run itself, its metrics, its
    quality events, and its incidents in one transaction, returning the
    generated ``validation_runs.id``.

    Takes only ``run`` -- its ``dataset`` field already carries the full
    Dataset object (see mapping.py's own docstring for why ``to_rows``
    doesn't accept a separate one).

    The dataset row is upserted on every call (``ON CONFLICT ... DO
    UPDATE``) rather than requiring a separate "register this dataset"
    step first -- a full dataset registry is out of scope for this
    milestone (docs/architecture/0003-milestone-2-architecture.md Part 1),
    so the dataset row's source of truth stays whatever local Dataset
    object the CLI just resolved from ``datasets/<name>.yaml``, refreshed
    into the store on every run rather than registered once and drifting.
    """
    persistable = to_rows(run)

    conn.begin()
    try:
        conn.execute(
            """
            INSERT INTO datasets
                (id, name, source_type, environment, owner, criticality, config_reference)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name,
                source_type = excluded.source_type,
                environment = excluded.environment,
                owner = excluded.owner,
                criticality = excluded.criticality,
                config_reference = excluded.config_reference
            """,
            [
                persistable.dataset.id,
                persistable.dataset.name,
                persistable.dataset.source_type,
                persistable.dataset.environment,
                persistable.dataset.owner,
                persistable.dataset.criticality,
                persistable.dataset.config_reference,
            ],
        )

        conn.execute(
            """
            INSERT INTO validation_runs
                (id, dataset_id, policy_version, started_at, finished_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                persistable.run.id,
                persistable.run.dataset_id,
                persistable.run.policy_version,
                persistable.run.started_at,
                persistable.run.finished_at,
                persistable.run.status,
            ],
        )

        for metric in persistable.metrics:
            conn.execute(
                """
                INSERT INTO metrics (id, validation_run_id, metric_name, value, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    metric.id,
                    metric.validation_run_id,
                    metric.metric_name,
                    metric.value,
                    metric.computed_at,
                ],
            )

        for event in persistable.events:
            conn.execute(
                """
                INSERT INTO quality_events
                    (id, validation_run_id, metric_id, status, expected,
                     strategy_type, severity, blocking, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    event.id,
                    event.validation_run_id,
                    event.metric_id,
                    event.status,
                    event.expected,
                    event.strategy_type,
                    event.severity,
                    event.blocking,
                    event.details,
                ],
            )

        for incident in persistable.incidents:
            conn.execute(
                """
                INSERT INTO incidents
                    (id, validation_run_id, quality_event_id, priority, score,
                     components, reasons)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    incident.id,
                    incident.validation_run_id,
                    incident.quality_event_id,
                    incident.priority,
                    incident.score,
                    incident.components,
                    incident.reasons,
                ],
            )
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()

    return persistable.run.id
