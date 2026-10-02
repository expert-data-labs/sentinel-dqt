"""SeasonalBaselineStrategy: mean/stdev band using only history from the same
weekday.

Stops false alarms on data with a weekly pattern (e.g. lower volume on
weekends).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, ClassVar

from sentinel.domain import Metric, Status, ThresholdConfig, ThresholdResult
from sentinel.thresholds._stats import mean_stddev_bounds
from sentinel.thresholds.base import InsufficientHistoryError, ThresholdConfigError
from sentinel.thresholds.registry import register_threshold_strategy

_DEFAULT_DIMENSION = "day_of_week"
_SUPPORTED_DIMENSIONS = frozenset({"day_of_week"})
_DEFAULT_N_SIGMA = 3.0
_DEFAULT_MIN_HISTORY = 2
_HARD_MINIMUM = 2  # mean_stddev_bounds needs at least 2 values per bucket

_WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def _describe_expectation(
    metric_name: str,
    bucket_name: str,
    lower: float,
    upper: float,
    mean: float,
    n_sigma: float,
    n: int,
) -> str:
    return (
        f"{metric_name} within [{lower:.4g}, {upper:.4g}] for {bucket_name} "
        f"(mean={mean:.4g}, ±{n_sigma:g}σ, n={n})"
    )


@register_threshold_strategy
class SeasonalBaselineStrategy:
    """Mean/stdev band built from past Metrics on the same day of the week.

    Params:

    - ``dimension`` (default and only option: ``day_of_week``)
    - ``n_sigma`` (default 3.0)
    - ``min_history`` (default 2, minimum 2): counted within the matching
      weekday only
    """

    strategy_type: ClassVar[str] = "seasonal"

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        dimension = config.params.get("dimension", _DEFAULT_DIMENSION)
        if dimension not in _SUPPORTED_DIMENSIONS:
            raise ThresholdConfigError(
                f"seasonal threshold for {metric.metric_name!r} has unsupported "
                f"dimension {dimension!r}; supported: {sorted(_SUPPORTED_DIMENSIONS)}"
            )

        n_sigma = config.params.get("n_sigma", _DEFAULT_N_SIGMA)
        min_history = max(config.params.get("min_history", _DEFAULT_MIN_HISTORY), _HARD_MINIMUM)

        bucket_index = metric.computed_at.weekday()
        bucket_name = _WEEKDAY_NAMES[bucket_index]
        bucket_history = [h for h in history if h.computed_at.weekday() == bucket_index]

        if len(bucket_history) < min_history:
            raise InsufficientHistoryError(
                f"seasonal threshold for {metric.metric_name!r} requires at least "
                f"{min_history} historical {bucket_name} metrics, got {len(bucket_history)} "
                f"({len(history)} historical metrics total, across all days)"
            )

        values = [h.value for h in bucket_history]
        bounds = mean_stddev_bounds(values, n_sigma)

        status = Status.PASS if bounds.lower <= metric.value <= bounds.upper else Status.FAIL

        details: dict[str, Any] = {
            "method": "seasonal_mean_stddev",
            "dimension": dimension,
            "bucket": bucket_name,
            "actual": metric.value,
            "mean": bounds.center,
            "stddev": bounds.spread,
            "lower": bounds.lower,
            "upper": bounds.upper,
            "n_sigma": n_sigma,
            "n_history_in_bucket": len(values),
            "n_history_total": len(history),
        }

        return ThresholdResult(
            status=status,
            expected=_describe_expectation(
                metric.metric_name,
                bucket_name,
                bounds.lower,
                bounds.upper,
                bounds.center,
                n_sigma,
                len(values),
            ),
            strategy_type=self.strategy_type,
            details=json.dumps(details),
        )
