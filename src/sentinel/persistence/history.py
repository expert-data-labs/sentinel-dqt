"""Postgres-backed HistoricalMetricsSource.

Reads past metric values from the ``metrics`` table. Lives here so
sentinel.thresholds never imports a database driver.
"""

from __future__ import annotations

from collections.abc import Sequence

from sentinel.domain import Metric
from sentinel.persistence.engine import StoreConnection

_DEFAULT_LIMIT = 90


class PostgresHistoricalMetricsSource:
    """Past Metrics from the store, newest first, capped at ``limit`` rows."""

    def __init__(self, conn: StoreConnection, limit: int = _DEFAULT_LIMIT) -> None:
        self._conn = conn
        self._limit = limit

    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]:
        rows = self._conn.execute(
            """
            SELECT m.value, m.computed_at
            FROM metrics m
            JOIN validation_runs vr ON vr.id = m.validation_run_id
            WHERE vr.dataset_id = %s AND m.metric_name = %s
            ORDER BY m.computed_at DESC
            LIMIT %s
            """,
            [dataset_id, metric_name, self._limit],
        ).fetchall()

        return tuple(
            Metric(metric_name=metric_name, value=value, computed_at=computed_at)
            for value, computed_at in rows
        )
