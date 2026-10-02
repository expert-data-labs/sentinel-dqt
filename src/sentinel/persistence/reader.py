"""Reads a short summary of past runs for ``sentinel history``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sentinel.domain import Status
from sentinel.persistence.engine import StoreConnection


@dataclass(frozen=True)
class RunSummary:
    """One stored run, projected down to what a history listing shows."""

    run_id: uuid.UUID
    started_at: datetime
    status: Status
    failed_rules: tuple[str, ...]


def list_recent_runs(conn: StoreConnection, dataset_name: str, limit: int = 10) -> list[RunSummary]:
    """The ``limit`` most recent runs for a dataset name, newest first, in one query."""
    rows = conn.execute(
        """
        SELECT r.id, r.started_at, r.status,
               COALESCE(
                   array_agg(m.metric_name ORDER BY m.metric_name)
                       FILTER (WHERE qe.status = %s),
                   ARRAY[]::text[]
               ) AS failed_rules
        FROM (
            SELECT vr.id, vr.started_at, vr.status
            FROM validation_runs vr
            JOIN datasets d ON d.id = vr.dataset_id
            WHERE d.name = %s
            ORDER BY vr.started_at DESC
            LIMIT %s
        ) r
        LEFT JOIN quality_events qe ON qe.validation_run_id = r.id
        LEFT JOIN metrics m ON m.id = qe.metric_id
        GROUP BY r.id, r.started_at, r.status
        ORDER BY r.started_at DESC
        """,
        (Status.FAIL.value, dataset_name, limit),
    ).fetchall()

    return [
        RunSummary(
            run_id=run_id,
            started_at=started_at,
            status=Status(status),
            failed_rules=tuple(failed_rules),
        )
        for run_id, started_at, status, failed_rules in rows
    ]
