"""StatisticalThresholdStrategy: judge a Metric against a
mean +/- n_sigma * standard-deviation band computed from its history.

Delegates the actual bound math to sentinel.thresholds._stats
(mean_stddev_bounds) rather than reimplementing it — see that module's
docstring for why it's shared with MedianMadStrategy rather than each
strategy owning a private copy.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, ClassVar

from sentinel.domain import Metric, Status, ThresholdConfig, ThresholdResult
from sentinel.thresholds._stats import mean_stddev_bounds
from sentinel.thresholds.base import InsufficientHistoryError
from sentinel.thresholds.registry import register_threshold_strategy

_DEFAULT_N_SIGMA = 3.0
_DEFAULT_MIN_HISTORY = 2
_HARD_MINIMUM = 2  # statistics.stdev is undefined below this, regardless of config


def _describe_expectation(
    metric_name: str, lower: float, upper: float, mean: float, n_sigma: float, n: int
) -> str:
    return (
        f"{metric_name} within [{lower:.4g}, {upper:.4g}] "
        f"(mean={mean:.4g}, ±{n_sigma:g}σ, n={n})"
    )


@register_threshold_strategy
class StatisticalThresholdStrategy:
    """Judges a Metric against ``mean(history) +/- n_sigma * stdev(history)``.

    ``config.params``:
        n_sigma (default 3.0): how many standard deviations from the mean
            still count as acceptable.
        min_history (default 2): the fewest historical Metrics required.
            Clamped up to 2 regardless of what's configured lower, since
            a standard deviation is undefined for fewer than two values —
            this is a hard mathematical floor, not a policy choice.

    Assumes ``history``'s values are approximately normally distributed:
    a mean and standard deviation describe a genuinely "typical range"
    only under something like that assumption. This is not checked or
    enforced — a skewed or multimodal history will still produce a
    number, just not a meaningful one. MedianMadStrategy is the
    documented alternative when a history is known or suspected to
    contain outliers or a non-normal shape (see its own docstring, and
    docs/architecture/0005-milestone-4-design.md Part 6/7 for a worked
    comparison on an outlier-contaminated history).
    """

    strategy_type: ClassVar[str] = "statistical"

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        n_sigma = config.params.get("n_sigma", _DEFAULT_N_SIGMA)
        min_history = max(config.params.get("min_history", _DEFAULT_MIN_HISTORY), _HARD_MINIMUM)

        if len(history) < min_history:
            raise InsufficientHistoryError(
                f"statistical threshold for {metric.metric_name!r} requires at least "
                f"{min_history} historical metrics, got {len(history)}"
            )

        values = [m.value for m in history]
        bounds = mean_stddev_bounds(values, n_sigma)

        status = Status.PASS if bounds.lower <= metric.value <= bounds.upper else Status.FAIL

        details: dict[str, Any] = {
            "method": "mean_stddev",
            "actual": metric.value,
            "mean": bounds.center,
            "stddev": bounds.spread,
            "lower": bounds.lower,
            "upper": bounds.upper,
            "n_sigma": n_sigma,
            "n_history": len(values),
        }

        return ThresholdResult(
            status=status,
            expected=_describe_expectation(
                metric.metric_name, bounds.lower, bounds.upper, bounds.center, n_sigma, len(values)
            ),
            strategy_type=self.strategy_type,
            details=json.dumps(details),
        )
