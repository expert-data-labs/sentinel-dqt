"""Reads a thin projection of stored validation history back out — not a
reconstructed domain object graph.

One function, shaped around exactly what ``sentinel history`` needs — see
docs/architecture/0003-milestone-2-architecture.md Part 5/Part 6 for why
this stays a projection (run id, started_at, status, failing rule names)
rather than a ``from_rows()`` counterpart to ``mapping.to_rows()``.
Nothing today needs a full ``ValidationRun`` rebuilt from stored rows,
and building that mapper would solve a problem nothing asks for yet.
"""

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
    """The ``limit`` most recent runs against the dataset named
    ``dataset_name`` (a Dataset's ``name``, not necessarily its ``id`` —
    they're equal in this milestone's fixtures but not guaranteed to be
    in general), most recent first.

    Fetches each run's failing rule names with one query per run rather
    than a single aggregating join — an N+1 pattern that's a deliberate
    simplicity trade-off, not an oversight: ``limit`` defaults to 10,
    every query here is a local embedded DuckDB file with no network
    round-trip, and a single ``list()``/``FILTER`` aggregate query would
    trade a few extra local queries for real complexity. Revisit if
    ``limit`` ever needs to be large.
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
