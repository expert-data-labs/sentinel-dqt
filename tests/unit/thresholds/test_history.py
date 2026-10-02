"""NullHistorySource contract; typed assignments let mypy check the Protocol."""

from __future__ import annotations

from sentinel.thresholds.history import HistoricalMetricsSource, NullHistorySource


def test_returns_empty_sequence_regardless_of_arguments() -> None:
    source: HistoricalMetricsSource = NullHistorySource()

    assert source.get_history("orders", "row_count") == ()
    assert source.get_history("anything", "anything_else") == ()


def test_returns_empty_sequence_for_repeated_calls() -> None:
    """Repeated calls keep returning empty."""
    source: HistoricalMetricsSource = NullHistorySource()

    first = source.get_history("orders", "row_count")
    second = source.get_history("orders", "row_count")

    assert first == second == ()
