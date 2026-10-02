"""DuckDB-backed FailureHistorySource.

Reads past statuses from ``quality_events``. Lives here so
sentinel.prioritization never imports duckdb.
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb

from sentinel.domain import Status

_DEFAULT_LIMIT = 90


class DuckDBFailureHistorySource:
    """Past statuses for one rule from the store, newest first, capped at ``limit``
    rows.
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
