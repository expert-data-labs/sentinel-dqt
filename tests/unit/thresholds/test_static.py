from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from sentinel.domain import Metric, Status, ThresholdConfig
from sentinel.thresholds.base import ThresholdConfigError
from sentinel.thresholds.static import StaticThresholdStrategy


def _metric(value: float) -> Metric:
    return Metric(metric_name="row_count", value=value, computed_at=datetime.now(UTC))


def _config(**params: Any) -> ThresholdConfig:
    return ThresholdConfig(strategy="static", params=params)


def test_min_only_passes_at_and_above_the_bound() -> None:
    strategy = StaticThresholdStrategy()
    config = _config(min=1000)

    assert strategy.evaluate(_metric(1000), config).status is Status.PASS
    assert strategy.evaluate(_metric(1500), config).status is Status.PASS


def test_min_only_fails_below_the_bound() -> None:
    strategy = StaticThresholdStrategy()
    result = strategy.evaluate(_metric(999), _config(min=1000))
    assert result.status is Status.FAIL


def test_max_only_passes_at_and_below_the_bound() -> None:
    strategy = StaticThresholdStrategy()
    config = _config(max=0.01)

    assert strategy.evaluate(_metric(0.01), config).status is Status.PASS
    assert strategy.evaluate(_metric(0.0), config).status is Status.PASS


def test_max_only_fails_above_the_bound() -> None:
    strategy = StaticThresholdStrategy()
    result = strategy.evaluate(_metric(0.02), _config(max=0.01))
    assert result.status is Status.FAIL


def test_range_passes_inside_and_at_both_boundaries() -> None:
    strategy = StaticThresholdStrategy()
    config = _config(min=10, max=100)

    assert strategy.evaluate(_metric(10), config).status is Status.PASS
    assert strategy.evaluate(_metric(55), config).status is Status.PASS
    assert strategy.evaluate(_metric(100), config).status is Status.PASS


def test_range_fails_outside_either_boundary() -> None:
    strategy = StaticThresholdStrategy()
    config = _config(min=10, max=100)

    assert strategy.evaluate(_metric(9), config).status is Status.FAIL
    assert strategy.evaluate(_metric(101), config).status is Status.FAIL


def test_neither_min_nor_max_raises_threshold_config_error() -> None:
    strategy = StaticThresholdStrategy()
    with pytest.raises(ThresholdConfigError, match="min.*max"):
        strategy.evaluate(_metric(42), _config())


def test_expected_string_is_readable_and_references_the_metric_name() -> None:
    strategy = StaticThresholdStrategy()
    result = strategy.evaluate(_metric(1500), _config(min=1000))
    assert result.expected == "row_count >= 1000"

    result = strategy.evaluate(_metric(0.0), _config(max=0.01))
    assert result.expected == "row_count <= 0.01"

    result = strategy.evaluate(_metric(55), _config(min=10, max=100))
    assert result.expected == "10 <= row_count <= 100"


def test_strategy_registers_itself_under_static() -> None:
    assert StaticThresholdStrategy.strategy_type == "static"
