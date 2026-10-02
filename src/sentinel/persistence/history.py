"""DuckDB-backed HistoricalMetricsSource.

Reads past metric values from the ``metrics`` table. Lives here so
sentinel.thresholds never imports duckdb.
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb

from sentinel.domain import Metric

_DEFAULT_LIMIT = 90


class DuckDBHistoricalMetricsSource:
    """Past Metrics from the store, newest first, capped at ``limit`` rows."""

    def __init__(
        self, conn: duckdb.DuckDBPyConnection, limit: int = _DEFAULT_LIMIT
    ) -> None:
        self._conn = conn
        self._limit = limit

    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]:
        rows = self._conn.execute(
            """
            SELECT m.value, m.computed_at
            FROM metrics m
            JOIN validation_runs vr ON vr.id = m.validation_run_id
            WHERE vr.dataset_id = ? AND m.metric_name = ?
            ORDER BY m.computed_at DESC
            LIMIT ?
            """,
            [dataset_id, metric_name, self._limit],
        ).fetchall()

        return tuple(
            Metric(metric_name=metric_name, value=value, computed_at=computed_at)
            for value, computed_at in rows
        )
