"""DuckDBHistoricalMetricsSource: the concrete, DuckDB-backed
implementation of sentinel.thresholds.history.HistoricalMetricsSource.

Lives here, not in sentinel.thresholds, precisely so thresholds/ never
imports duckdb — see thresholds/history.py's own docstring and
docs/architecture/0005-milestone-4-design.md Part 2 for why that
separation is the point of the abstraction, not an accident of file
layout.

Queries the same ``metrics`` table persistence/writer.py already
populates, joined to ``validation_runs`` on ``validation_run_id`` — no
schema migration for Milestone 4. Unlike persistence/reader.py's
``list_recent_runs`` (which filters by a Dataset's ``name`` and therefore
needs a further join to ``datasets``), this filters directly on
``validation_runs.dataset_id``, which is already the same string as
Dataset.id — the id ``HistoricalMetricsSource.get_history`` is scoped by
(see thresholds/history.py) — so no second join is needed here.
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb

from sentinel.domain import Metric

_DEFAULT_LIMIT = 90


class DuckDBHistoricalMetricsSource:
    """A HistoricalMetricsSource backed by Sentinel's own persistence
    store (persistence/engine.py — always DuckDB, unlike the pluggable
    DataSource a Dataset's own data lives behind; see the design doc for
    why that distinction means this class needs no registry or
    adapter-per-backend pattern the way DataSource does).

    ``limit`` caps how many rows one ``get_history()`` call returns (most
    recent first), so a long-lived dataset's validation history doesn't
    grow the query cost of every future run. HistoricalMetricsSource's
    own contract makes no promise about totality for exactly this reason
    — each ThresholdStrategy's own ``min_history`` param decides how much
    of what's returned it actually needs.
    """

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
