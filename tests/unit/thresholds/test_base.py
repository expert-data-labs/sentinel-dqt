"""InsufficientHistoryError and ThresholdConfigError must stay distinct."""

from __future__ import annotations

from sentinel.thresholds.base import InsufficientHistoryError, ThresholdConfigError


def test_insufficient_history_error_is_not_a_threshold_config_error() -> None:
    assert not issubclass(InsufficientHistoryError, ThresholdConfigError)
    assert not issubclass(ThresholdConfigError, InsufficientHistoryError)


def test_insufficient_history_error_is_raisable_and_catchable() -> None:
    try:
        raise InsufficientHistoryError("need at least 2 historical metrics, got 0")
    except InsufficientHistoryError as exc:
        assert "need at least 2" in str(exc)
