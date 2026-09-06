"""Pins NullHistorySource's contract, and proves — via the
HistoricalMetricsSource-typed variable each test assigns through — that it
satisfies the Protocol structurally (checked by mypy, not at runtime;
HistoricalMetricsSource has no @runtime_checkable marker, matching every
other Protocol in this codebase — see tests/unit/datasources/test_base.py)."""

from __future__ import annotations

from sentinel.thresholds.history import HistoricalMetricsSource, NullHistorySource


def test_returns_empty_sequence_regardless_of_arguments() -> None:
    source: HistoricalMetricsSource = NullHistorySource()

    assert source.get_history("orders", "row_count") == ()
    assert source.get_history("anything", "anything_else") == ()


def test_returns_empty_sequence_for_repeated_calls() -> None:
    """Not stateful — calling it twice for the same key doesn't start
    returning something different the second time."""
    source: HistoricalMetricsSource = NullHistorySource()

    first = source.get_history("orders", "row_count")
    second = source.get_history("orders", "row_count")

    assert first == second == ()
