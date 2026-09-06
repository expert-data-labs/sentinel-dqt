from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from sentinel.domain import Metric, Status, ThresholdConfig
from sentinel.thresholds.base import InsufficientHistoryError, ThresholdConfigError
from sentinel.thresholds.seasonal import SeasonalBaselineStrategy

# 2026-09-07 is a Monday; 2026-09-12 is a Saturday (confirmed via Python's
# own calendar -- kept as a plain comment rather than computed, so a typo
# here is caught by the very assertions that rely on it lining up).
_MONDAY = datetime(2026, 9, 7, tzinfo=UTC)
_TUESDAY = datetime(2026, 9, 8, tzinfo=UTC)
_SATURDAY = datetime(2026, 9, 12, tzinfo=UTC)
_SUNDAY = datetime(2026, 9, 13, tzinfo=UTC)


def _metric(value: float, computed_at: datetime) -> Metric:
    return Metric(metric_name="row_count", value=value, computed_at=computed_at)


def _config(**params: Any) -> ThresholdConfig:
    return ThresholdConfig(strategy="seasonal", params=params)


# Small deterministic per-week variation (not all-identical values) so a
# bucket's bounds are a real, nonzero-width interval rather than
# collapsing to a single point -- a bucket of four identical values would
# make "505 passes for Saturday" indistinguishable from "505 passes only
# because it happens to equal every historical Saturday exactly."
_OFFSET_PATTERN = (-5.0, 0.0, 5.0, 0.0)


def _weekly_history(
    weekday_values: float, weekend_values: float, weeks: int
) -> tuple[Metric, ...]:
    """``weeks`` Mondays at ``weekday_values`` (+/- a small offset) and
    ``weeks`` Saturdays at ``weekend_values`` (+/- the same offset) --
    the Scenario B shape (weekday/weekend split)."""
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
    """1000 every Monday, 500 every Saturday. A Saturday value of 500 is
    perfectly normal for Saturday, but would look like a huge deviation
    against a global (all-days) mean -- this is Scenario B's whole point."""
    strategy = SeasonalBaselineStrategy()
    history = _weekly_history(weekday_values=1000.0, weekend_values=500.0, weeks=4)

    saturday_result = strategy.evaluate(
        _metric(505.0, _SATURDAY + timedelta(weeks=4)), _config(n_sigma=3.0), history
    )

    assert saturday_result.status is Status.PASS


def test_a_weekday_value_at_the_weekend_level_is_flagged() -> None:
    """The same 500 evaluated as if it were a Monday -- normal for
    Saturday, not normal for Monday -- is exactly the false positive a
    seasonal baseline exists to distinguish from a genuine anomaly, in
    the other direction: here it's correctly still a genuine anomaly for
    the bucket it's actually being judged against."""
    strategy = SeasonalBaselineStrategy()
    history = _weekly_history(weekday_values=1000.0, weekend_values=500.0, weeks=4)

    monday_result = strategy.evaluate(
        _metric(500.0, _MONDAY + timedelta(weeks=4)), _config(n_sigma=3.0), history
    )

    assert monday_result.status is Status.FAIL


def test_insufficient_history_in_the_current_bucket_raises_even_with_plenty_overall() -> None:
    """Four Mondays of history but zero Tuesdays -- evaluating a Tuesday
    metric must not silently borrow Monday's baseline."""
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
