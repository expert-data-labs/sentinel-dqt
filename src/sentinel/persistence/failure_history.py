"""Postgres-backed FailureHistorySource.

Reads past statuses from ``quality_events``. Lives here so
sentinel.prioritization never imports a database driver.
"""

from __future__ import annotations

from collections.abc import Sequence

from sentinel.domain import Status
from sentinel.persistence.engine import StoreConnection

_DEFAULT_LIMIT = 90


class PostgresFailureHistorySource:
    """Past statuses for one rule from the store, newest first, capped at ``limit``
    rows.
    """

    def __init__(self, conn: StoreConnection, limit: int = _DEFAULT_LIMIT) -> None:
        self._conn = conn
        self._limit = limit

    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        rows = self._conn.execute(
            """
            SELECT qe.status
            FROM quality_events qe
            JOIN metrics m ON m.id = qe.metric_id
            JOIN validation_runs vr ON vr.id = qe.validation_run_id
            WHERE vr.dataset_id = %s AND m.metric_name = %s
            ORDER BY m.computed_at DESC
            LIMIT %s
            """,
            [dataset_id, metric_name, self._limit],
        ).fetchall()

        return tuple(Status(status) for (status,) in rows)
