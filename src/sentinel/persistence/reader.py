"""Reads a short summary of past runs for ``sentinel history``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import duckdb

from sentinel.domain import Status


@dataclass(frozen=True)
class RunSummary:
    """One stored run, projected down to what a history listing shows."""

    run_id: uuid.UUID
    started_at: datetime
    status: Status
    failed_rules: tuple[str, ...]


def _failed_rule_names(conn: duckdb.DuckDBPyConnection, run_id: uuid.UUID) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT m.metric_name
        FROM quality_events qe
        JOIN metrics m ON m.id = qe.metric_id
        WHERE qe.validation_run_id = ? AND qe.status = ?
        ORDER BY m.metric_name
        """,
        [run_id, Status.FAIL.value],
    ).fetchall()
    return tuple(row[0] for row in rows)


def list_recent_runs(
    conn: duckdb.DuckDBPyConnection, dataset_name: str, limit: int = 10
) -> list[RunSummary]:
    """The ``limit`` most recent runs for a dataset name, newest first.

    Uses one query per run for failed rules; fine for small limits on a local
    DuckDB file.
    """
    rows = conn.execute(
        """
        SELECT vr.id, vr.started_at, vr.status
        FROM validation_runs vr
        JOIN datasets d ON d.id = vr.dataset_id
        WHERE d.name = ?
        ORDER BY vr.started_at DESC
        LIMIT ?
        """,
        [dataset_name, limit],
    ).fetchall()

    return [
        RunSummary(
            run_id=run_id,
            started_at=started_at,
            status=Status(status),
            failed_rules=_failed_rule_names(conn, run_id),
        )
        for run_id, started_at, status in rows
    ]
