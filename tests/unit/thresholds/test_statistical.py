from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from sentinel.domain import Metric, Status, ThresholdConfig
from sentinel.thresholds.base import InsufficientHistoryError
from sentinel.thresholds.statistical import StatisticalThresholdStrategy


def _metric(value: float) -> Metric:
    return Metric(metric_name="row_count", value=value, computed_at=datetime.now(UTC))


def _config(**params: Any) -> ThresholdConfig:
    return ThresholdConfig(strategy="statistical", params=params)


def _history(*values: float) -> tuple[Metric, ...]:
    return tuple(_metric(v) for v in values)


def test_value_within_n_sigma_passes() -> None:
    strategy = StatisticalThresholdStrategy()
    history = _history(990.0, 1000.0, 1010.0)

    result = strategy.evaluate(_metric(1005.0), _config(n_sigma=3.0), history)

    assert result.status is Status.PASS


def test_value_far_outside_n_sigma_fails() -> None:
    strategy = StatisticalThresholdStrategy()
    history = _history(990.0, 1000.0, 1010.0)

    result = strategy.evaluate(_metric(1800.0), _config(n_sigma=3.0), history)

    assert result.status is Status.FAIL


def test_default_n_sigma_is_three() -> None:
    strategy = StatisticalThresholdStrategy()
    history = _history(990.0, 1000.0, 1010.0)

    result = strategy.evaluate(_metric(1005.0), _config(), history)

    assert result.status is Status.PASS


def test_zero_variance_history_only_passes_the_exact_value() -> None:
    strategy = StatisticalThresholdStrategy()
    history = _history(1000.0, 1000.0, 1000.0)

    exact = strategy.evaluate(_metric(1000.0), _config(n_sigma=3.0), history)
    off_by_one = strategy.evaluate(_metric(1000.01), _config(n_sigma=3.0), history)

    assert exact.status is Status.PASS
    assert off_by_one.status is Status.FAIL


def test_insufficient_history_raises() -> None:
    strategy = StatisticalThresholdStrategy()
    with pytest.raises(InsufficientHistoryError):
        strategy.evaluate(_metric(1000.0), _config(), _history(1000.0))


def test_no_history_raises() -> None:
    strategy = StatisticalThresholdStrategy()
    with pytest.raises(InsufficientHistoryError):
        strategy.evaluate(_metric(1000.0), _config(), ())


def test_configured_min_history_below_two_is_still_clamped_to_two() -> None:
    """A standard deviation is undefined for fewer than two values --
    this is a hard mathematical floor, not something a policy author can
    configure away."""
    strategy = StatisticalThresholdStrategy()
    with pytest.raises(InsufficientHistoryError):
        strategy.evaluate(_metric(1000.0), _config(min_history=1), _history(1000.0))


def test_details_records_mean_stddev_bounds_and_actual() -> None:
    strategy = StatisticalThresholdStrategy()
    history = _history(990.0, 1000.0, 1010.0)

    result = strategy.evaluate(_metric(1005.0), _config(n_sigma=3.0), history)

    details = json.loads(result.details or "{}")
    assert details["actual"] == 1005.0
    assert details["mean"] == pytest.approx(1000.0)
    assert details["n_sigma"] == 3.0
    assert details["n_history"] == 3
    assert details["lower"] < 1005.0 < details["upper"]


def test_strategy_registers_itself_under_statistical() -> None:
    assert StatisticalThresholdStrategy.strategy_type == "statistical"
