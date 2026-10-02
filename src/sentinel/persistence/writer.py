"""Writes a ValidationRun and everything it produced to the store."""

from __future__ import annotations

import uuid

from sentinel.domain import ValidationRun
from sentinel.persistence.engine import StoreConnection
from sentinel.persistence.mapping import to_rows


def persist_validation_run(conn: StoreConnection, run: ValidationRun) -> uuid.UUID:
    """Save the dataset, run, metrics, events and incidents in one transaction.

    The dataset row is upserted each time, so it always matches the YAML the CLI
    just loaded. Returns the new ``validation_runs.id``.
    """
    persistable = to_rows(run)

    with conn.transaction():
        conn.execute(
            """
            INSERT INTO datasets
                (id, name, source_type, environment, owner, criticality, config_reference)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name,
                source_type = excluded.source_type,
                environment = excluded.environment,
                owner = excluded.owner,
                criticality = excluded.criticality,
                config_reference = excluded.config_reference
            """,
            (
                persistable.dataset.id,
                persistable.dataset.name,
                persistable.dataset.source_type,
                persistable.dataset.environment,
                persistable.dataset.owner,
                persistable.dataset.criticality,
                persistable.dataset.config_reference,
            ),
        )

        conn.execute(
            """
            INSERT INTO validation_runs
                (id, dataset_id, policy_version, started_at, finished_at, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                persistable.run.id,
                persistable.run.dataset_id,
                persistable.run.policy_version,
                persistable.run.started_at,
                persistable.run.finished_at,
                persistable.run.status,
            ),
        )

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO metrics (id, validation_run_id, metric_name, value, computed_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (m.id, m.validation_run_id, m.metric_name, m.value, m.computed_at)
                    for m in persistable.metrics
                ],
            )
            cur.executemany(
                """
                INSERT INTO quality_events
                    (id, validation_run_id, metric_id, status, expected,
                     strategy_type, severity, blocking, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        e.id,
                        e.validation_run_id,
                        e.metric_id,
                        e.status,
                        e.expected,
                        e.strategy_type,
                        e.severity,
                        e.blocking,
                        e.details,
                    )
                    for e in persistable.events
                ],
            )
            if persistable.incidents:
                cur.executemany(
                    """
                    INSERT INTO incidents
                        (id, validation_run_id, quality_event_id, priority, score,
                         components, reasons)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            i.id,
                            i.validation_run_id,
                            i.quality_event_id,
                            i.priority,
                            i.score,
                            i.components,
                            i.reasons,
                        )
                        for i in persistable.incidents
                    ],
                )

    return persistable.run.id
