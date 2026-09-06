"""DuckDBFailureHistorySource: the concrete, DuckDB-backed implementation of
sentinel.prioritization.history.FailureHistorySource.

Lives here, not in sentinel.prioritization, for the same reason
persistence/history.py doesn't live in sentinel.thresholds: so
sentinel.prioritization never imports duckdb (see
sentinel.prioritization.history's own docstring).

Queries the same ``quality_events`` table persistence/writer.py already
populates, joined to ``metrics`` (for ``metric_name``) and
``validation_runs`` (for ``dataset_id`` and ordering by ``computed_at``) --
no schema migration for Milestone 5, exactly like Milestone 4's
DuckDBHistoricalMetricsSource needed none. Every column this query reads
(``quality_events.status``, ``metrics.metric_name``,
``validation_runs.dataset_id``) has been persisted since Milestone 2.
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb

from sentinel.domain import Status

_DEFAULT_LIMIT = 90


class DuckDBFailureHistorySource:
    """A FailureHistorySource backed by Sentinel's own persistence store
    (persistence/engine.py -- always DuckDB; see
    DuckDBHistoricalMetricsSource's own docstring for why this needs no
    registry or adapter-per-backend pattern the way DataSource does).

    ``limit`` caps how many rows one ``get_outcomes()`` call returns (most
    recent first), the same row-count-window trade-off
    DuckDBHistoricalMetricsSource already makes for the identical reason:
    a long-lived dataset's history shouldn't grow the query cost of every
    future run.
    """

    def __init__(
        self, conn: duckdb.DuckDBPyConnection, limit: int = _DEFAULT_LIMIT
    ) -> None:
        self._conn = conn
        self._limit = limit

    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        rows = self._conn.execute(
            """
            SELECT qe.status
            FROM quality_events qe
            JOIN metrics m ON m.id = qe.metric_id
            JOIN validation_runs vr ON vr.id = qe.validation_run_id
            WHERE vr.dataset_id = ? AND m.metric_name = ?
            ORDER BY m.computed_at DESC
            LIMIT ?
            """,
            [dataset_id, metric_name, self._limit],
        ).fetchall()

        return tuple(Status(status) for (status,) in rows)
