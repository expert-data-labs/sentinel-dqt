from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from sentinel.domain import Metric, Status, ThresholdConfig
from sentinel.thresholds.base import InsufficientHistoryError
from sentinel.thresholds.median_mad import MedianMadStrategy
from sentinel.thresholds.statistical import StatisticalThresholdStrategy


def _metric(value: float) -> Metric:
    return Metric(metric_name="row_count", value=value, computed_at=datetime.now(UTC))


def _config(strategy: str = "median_mad", **params: Any) -> ThresholdConfig:
    return ThresholdConfig(strategy=strategy, params=params)


def _history(*values: float) -> tuple[Metric, ...]:
    return tuple(_metric(v) for v in values)


def test_value_within_n_mad_passes() -> None:
    strategy = MedianMadStrategy()
    history = _history(990.0, 1000.0, 1010.0)

    result = strategy.evaluate(_metric(1005.0), _config(n_mad=3.0), history)

    assert result.status is Status.PASS


def test_value_far_outside_n_mad_fails() -> None:
    strategy = MedianMadStrategy()
    history = _history(990.0, 1000.0, 1010.0)

    result = strategy.evaluate(_metric(1800.0), _config(n_mad=3.0), history)

    assert result.status is Status.FAIL


def test_default_n_mad_is_three() -> None:
    strategy = MedianMadStrategy()
    history = _history(990.0, 1000.0, 1010.0)

    result = strategy.evaluate(_metric(1005.0), _config(), history)

    assert result.status is Status.PASS


def test_zero_mad_history_only_passes_the_exact_median() -> None:
    strategy = MedianMadStrategy()
    history = _history(1000.0, 1000.0, 1000.0, 1000.0, 5000.0)

    exact = strategy.evaluate(_metric(1000.0), _config(n_mad=3.0), history)
    off_by_one = strategy.evaluate(_metric(1000.01), _config(n_mad=3.0), history)

    assert exact.status is Status.PASS
    assert off_by_one.status is Status.FAIL


def test_insufficient_history_raises() -> None:
    strategy = MedianMadStrategy()
    config = _config(min_history=2)
    with pytest.raises(InsufficientHistoryError):
        strategy.evaluate(_metric(1000.0), config, _history(1000.0))


def test_details_records_median_mad_bounds_and_actual() -> None:
    strategy = MedianMadStrategy()
    history = _history(990.0, 1000.0, 1010.0)

    result = strategy.evaluate(_metric(1005.0), _config(n_mad=3.0), history)

    details = json.loads(result.details or "{}")
    assert details["actual"] == 1005.0
    assert details["median"] == pytest.approx(1000.0)
    assert details["n_mad"] == 3.0
    assert details["n_history"] == 3
    assert details["lower"] < 1005.0 < details["upper"]


def test_is_far_less_disturbed_by_a_historical_outlier_than_statistical() -> None:
    """Scenario D history: statistical misses the outlier, median/MAD catches it."""
    history = _history(1000.0, 1020.0, 980.0, 1010.0, 1005.0, 5000.0)
    outlier_sized_value = _metric(5000.0)

    statistical_result = StatisticalThresholdStrategy().evaluate(
        outlier_sized_value, _config(strategy="statistical", n_sigma=3.0), history
    )
    median_mad_result = MedianMadStrategy().evaluate(
        outlier_sized_value, _config(n_mad=3.0), history
    )

    assert statistical_result.status is Status.PASS  # false negative: hides inside its own bounds
    assert median_mad_result.status is Status.FAIL  # correctly rejected


def test_strategy_registers_itself_under_median_mad() -> None:
    assert MedianMadStrategy.strategy_type == "median_mad"
