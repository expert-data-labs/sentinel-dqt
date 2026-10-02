"""HistoricalMetricsSource: supplies the ``history`` passed to strategies.

The DuckDB implementation lives in sentinel.persistence so this package never
imports duckdb.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sentinel.domain import Metric


class HistoricalMetricsSource(Protocol):
    """Returns prior Metrics for one (dataset, metric name) pair.

    ``metric_name`` is the rule's configured name, so two rules of the same type
    keep separate histories.
    """

    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]:
        """Prior Metrics, most recent first. May be capped.

        Returns an empty sequence (never raises) when there is no history; the
        strategy decides whether that's enough.
        """
        ...


class NullHistorySource:
    """A HistoricalMetricsSource with no history. The orchestrator's default."""

    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]:
        return ()
