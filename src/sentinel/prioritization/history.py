"""FailureHistorySource: past pass/fail outcomes for one rule.

Separate from HistoricalMetricsSource, which returns values without statuses.
The Postgres implementation lives in sentinel.persistence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sentinel.domain import Status


class FailureHistorySource(Protocol):
    """Returns prior statuses for one (dataset, metric name) pair."""

    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        """Prior statuses, most recent first. May be capped by row count.

        Returns an empty sequence (never raises) when there is no history.
        """
        ...


class NullFailureHistorySource:
    """A FailureHistorySource with no history: every failure counts as a first
    occurrence.
    """

    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        return ()
