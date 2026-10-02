from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from sentinel.domain import Metric, Status, ThresholdConfig
from sentinel.thresholds.base import InsufficientHistoryError, ThresholdConfigError
from sentinel.thresholds.seasonal import SeasonalBaselineStrategy

# 2026-09-07 is a Monday; 2026-09-12 is a Saturday.
_MONDAY = datetime(2026, 9, 7, tzinfo=UTC)
_TUESDAY = datetime(2026, 9, 8, tzinfo=UTC)
_SATURDAY = datetime(2026, 9, 12, tzinfo=UTC)
_SUNDAY = datetime(2026, 9, 13, tzinfo=UTC)


def _metric(value: float, computed_at: datetime) -> Metric:
    return Metric(metric_name="row_count", value=value, computed_at=computed_at)


def _config(**params: Any) -> ThresholdConfig:
    return ThresholdConfig(strategy="seasonal", params=params)


# Small per-week variation so each bucket has a non-zero width.
_OFFSET_PATTERN = (-5.0, 0.0, 5.0, 0.0)


def _weekly_history(
    weekday_values: float, weekend_values: float, weeks: int
) -> tuple[Metric, ...]:
    """``weeks`` Mondays near ``weekday_values`` and Saturdays near ``weekend_values``."""
    history = []
    for week in range(weeks):
        offset = _OFFSET_PATTERN[week % len(_OFFSET_PATTERN)]
        history.append(_metric(weekday_values + offset, _MONDAY + timedelta(weeks=week)))
        history.append(_metric(weekend_values + offset, _SATURDAY + timedelta(weeks=week)))
    return tuple(history)


def test_confirms_the_weekday_fixtures_line_up() -> None:
    assert _MONDAY.weekday() == 0
    assert _TUESDAY.weekday() == 1
    assert _SATURDAY.weekday() == 5
    assert _SUNDAY.weekday() == 6


def test_evaluates_against_only_the_matching_weekday_bucket() -> None:
    """500 is normal for a Saturday even though the overall mean is higher."""
    strategy = SeasonalBaselineStrategy()
    history = _weekly_history(weekday_values=1000.0, weekend_values=500.0, weeks=4)

    saturday_result = strategy.evaluate(
        _metric(505.0, _SATURDAY + timedelta(weeks=4)), _config(n_sigma=3.0), history
    )

    assert saturday_result.status is Status.PASS


def test_a_weekday_value_at_the_weekend_level_is_flagged() -> None:
    """The same 500 on a Monday is an anomaly."""
    strategy = SeasonalBaselineStrategy()
    history = _weekly_history(weekday_values=1000.0, weekend_values=500.0, weeks=4)

    monday_result = strategy.evaluate(
        _metric(500.0, _MONDAY + timedelta(weeks=4)), _config(n_sigma=3.0), history
    )

    assert monday_result.status is Status.FAIL


def test_insufficient_history_in_the_current_bucket_raises_even_with_plenty_overall() -> None:
    """Monday history must not be used for a Tuesday."""
    strategy = SeasonalBaselineStrategy()
    history = tuple(
        _metric(1000.0, _MONDAY + timedelta(weeks=week)) for week in range(4)
    )

    with pytest.raises(InsufficientHistoryError):
        strategy.evaluate(_metric(1000.0, _TUESDAY), _config(n_sigma=3.0), history)


def test_unsupported_dimension_raises_threshold_config_error() -> None:
    strategy = SeasonalBaselineStrategy()
    history = _weekly_history(weekday_values=1000.0, weekend_values=500.0, weeks=4)

    with pytest.raises(ThresholdConfigError, match="dimension"):
        strategy.evaluate(
            _metric(1000.0, _MONDAY), _config(dimension="hour_of_day"), history
        )


def test_dimension_defaults_to_day_of_week() -> None:
    strategy = SeasonalBaselineStrategy()
    history = _weekly_history(weekday_values=1000.0, weekend_values=500.0, weeks=4)

    result = strategy.evaluate(
        _metric(1005.0, _MONDAY + timedelta(weeks=4)), _config(n_sigma=3.0), history
    )

    assert result.status is Status.PASS


def test_details_records_bucket_name_and_both_history_counts() -> None:
    strategy = SeasonalBaselineStrategy()
    history = _weekly_history(weekday_values=1000.0, weekend_values=500.0, weeks=4)

    result = strategy.evaluate(
        _metric(1005.0, _MONDAY + timedelta(weeks=4)), _config(n_sigma=3.0), history
    )

    details = json.loads(result.details or "{}")
    assert details["bucket"] == "Monday"
    assert details["n_history_in_bucket"] == 4
    assert details["n_history_total"] == 8


def test_strategy_registers_itself_under_seasonal() -> None:
    assert SeasonalBaselineStrategy.strategy_type == "seasonal"
