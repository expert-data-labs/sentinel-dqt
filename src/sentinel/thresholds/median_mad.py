"""MedianMadStrategy: median +/- n_mad * scaled MAD of history."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, ClassVar

from sentinel.domain import Metric, Status, ThresholdConfig, ThresholdResult
from sentinel.thresholds._stats import median_mad_bounds
from sentinel.thresholds.base import InsufficientHistoryError
from sentinel.thresholds.registry import register_threshold_strategy

_DEFAULT_N_MAD = 3.0
_DEFAULT_MIN_HISTORY = 2


def _describe_expectation(
    metric_name: str, lower: float, upper: float, median: float, n_mad: float, n: int
) -> str:
    return (
        f"{metric_name} within [{lower:.4g}, {upper:.4g}] "
        f"(median={median:.4g}, ±{n_mad:g} scaled MAD, n={n})"
    )


@register_threshold_strategy
class MedianMadStrategy:
    """Pass if the value is within ``median +/- n_mad * (1.4826 * MAD)``.

    Robust to outliers: one extreme past value can widen a mean/stdev band
    enough to hide real anomalies, but barely moves the median and MAD.

    Params:

    - ``n_mad`` (default 3.0), comparable to ``n_sigma``
    - ``min_history`` (default 2)
    """

    strategy_type: ClassVar[str] = "median_mad"

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        n_mad = config.params.get("n_mad", _DEFAULT_N_MAD)
        min_history = config.params.get("min_history", _DEFAULT_MIN_HISTORY)

        if len(history) < min_history:
            raise InsufficientHistoryError(
                f"median_mad threshold for {metric.metric_name!r} requires at least "
                f"{min_history} historical metrics, got {len(history)}"
            )

        values = [m.value for m in history]
        bounds = median_mad_bounds(values, n_mad)

        status = Status.PASS if bounds.lower <= metric.value <= bounds.upper else Status.FAIL

        details: dict[str, Any] = {
            "method": "median_mad",
            "actual": metric.value,
            "median": bounds.center,
            "mad_scaled": bounds.spread,
            "lower": bounds.lower,
            "upper": bounds.upper,
            "n_mad": n_mad,
            "n_history": len(values),
        }

        return ThresholdResult(
            status=status,
            expected=_describe_expectation(
                metric.metric_name, bounds.lower, bounds.upper, bounds.center, n_mad, len(values)
            ),
            strategy_type=self.strategy_type,
            details=json.dumps(details),
        )
