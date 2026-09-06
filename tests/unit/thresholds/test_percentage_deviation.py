from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from sentinel.domain import Metric, Status, ThresholdConfig
from sentinel.thresholds.base import InsufficientHistoryError, ThresholdConfigError
from sentinel.thresholds.percentage_deviation import PercentageDeviationStrategy


def _metric(value: float) -> Metric:
    return Metric(metric_name="row_count", value=value, computed_at=datetime.now(UTC))


def _config(**params: Any) -> ThresholdConfig:
    return ThresholdConfig(strategy="percentage_deviation", params=params)


def _history(*values: float) -> tuple[Metric, ...]:
    return tuple(_metric(v) for v in values)


def test_within_max_deviation_passes() -> None:
    strategy = PercentageDeviationStrategy()
    history = _history(990.0, 1000.0, 1010.0)  # mean = 1000.0

    result = strategy.evaluate(_metric(1080.0), _config(max_deviation=0.10), history)

    assert result.status is Status.PASS


def test_beyond_max_deviation_fails() -> None:
    strategy = PercentageDeviationStrategy()
    history = _history(990.0, 1000.0, 1010.0)  # mean = 1000.0

    result = strategy.evaluate(_metric(1200.0), _config(max_deviation=0.10), history)

    assert result.status is Status.FAIL


def test_exactly_at_max_deviation_passes() -> None:
    strategy = PercentageDeviationStrategy()
    history = _history(1000.0, 1000.0)  # mean = 1000.0

    result = strategy.evaluate(_metric(1100.0), _config(max_deviation=0.10), history)

    assert result.status is Status.PASS


def test_negative_baseline_uses_absolute_relative_deviation() -> None:
    """A rule whose value can legitimately go negative (e.g. a signed
    balance metric) shouldn't need special config -- the formula is
    symmetric in sign once the comparison uses abs()."""
    strategy = PercentageDeviationStrategy()
    history = _history(-100.0, -100.0)  # mean = -100.0

    within = strategy.evaluate(_metric(-108.0), _config(max_deviation=0.10), history)
    beyond = strategy.evaluate(_metric(-130.0), _config(max_deviation=0.10), history)

    assert within.status is Status.PASS
    assert beyond.status is Status.FAIL


def test_zero_baseline_and_zero_actual_passes() -> None:
    strategy = PercentageDeviationStrategy()
    history = _history(0.0, 0.0)

    result = strategy.evaluate(_metric(0.0), _config(max_deviation=0.10), history)

    assert result.status is Status.PASS
    details = json.loads(result.details or "{}")
    assert details["deviation"] == 0.0


def test_zero_baseline_and_nonzero_actual_fails_with_undefined_deviation() -> None:
    strategy = PercentageDeviationStrategy()
    history = _history(0.0, 0.0)

    result = strategy.evaluate(_metric(500.0), _config(max_deviation=0.10), history)

    assert result.status is Status.FAIL
    details = json.loads(result.details or "{}")
    assert details["deviation"] is None
    assert "note" in details


def test_missing_max_deviation_raises_threshold_config_error() -> None:
    strategy = PercentageDeviationStrategy()
    with pytest.raises(ThresholdConfigError, match="max_deviation"):
        strategy.evaluate(_metric(1000.0), _config(), _history(1000.0))


def test_insufficient_history_raises() -> None:
    strategy = PercentageDeviationStrategy()
    config = _config(max_deviation=0.10, min_history=2)
    with pytest.raises(InsufficientHistoryError):
        strategy.evaluate(_metric(1000.0), config, _history(1000.0))


def test_default_min_history_is_one() -> None:
    """No min_history configured -> a single historical point is enough
    to compute a baseline (see the strategy's own docstring)."""
    strategy = PercentageDeviationStrategy()
    result = strategy.evaluate(_metric(1000.0), _config(max_deviation=0.10), _history(1000.0))
    assert result.status is Status.PASS


def test_details_records_baseline_actual_deviation_and_allowed_deviation() -> None:
    strategy = PercentageDeviationStrategy()
    history = _history(1000.0, 1000.0)

    result = strategy.evaluate(_metric(1200.0), _config(max_deviation=0.10), history)

    details = json.loads(result.details or "{}")
    assert details["actual"] == 1200.0
    assert details["baseline"] == 1000.0
    assert details["deviation"] == pytest.approx(0.20)
    assert details["max_deviation"] == 0.10
    assert details["n_history"] == 2


def test_strategy_registers_itself_under_percentage_deviation() -> None:
    assert PercentageDeviationStrategy.strategy_type == "percentage_deviation"
