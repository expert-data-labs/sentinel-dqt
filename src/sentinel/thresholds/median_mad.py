"""MedianMadStrategy: judge a Metric against a
median +/- n_mad * scaled-MAD band computed from its history.

The robust counterpart to StatisticalThresholdStrategy. Delegates the
actual bound math to sentinel.thresholds._stats (median_mad_bounds) —
see that module's docstring for the shared-helper reasoning.
"""

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
    """Judges a Metric against
    ``median(history) +/- n_mad * (1.4826 * MAD(history))``.

    Why prefer this over Mean/StdDev when history might contain an
    outlier: a mean is the arithmetic average of every value, so one
    extreme historical point (a one-off outage, a bad backfill, a
    logging glitch) can drag it arbitrarily far, and inflate the standard
    deviation right along with it — widening the "acceptable" band until
    the outlier itself looks normal and genuine anomalies of a similar
    size stop being flagged. A median only asks "what's the middle
    value," so one extreme point moves it by at most one rank position;
    the Median Absolute Deviation, being itself a median (of absolute
    deviations from the median), is similarly insensitive. See
    docs/architecture/0005-milestone-4-design.md Part 6/7 for a worked
    comparison — the identical history that pushes Mean/StdDev's bounds
    wide enough to accept a 5x outlier leaves Median/MAD's bounds
    correctly rejecting it.

    ``config.params``:
        n_mad (default 3.0): how many scaled-MAD units from the median
            still count as acceptable — comparable in spirit to
            ``n_sigma`` on the Statistical strategy (see
            sentinel.thresholds._stats's scaling-constant note).
        min_history (default 2): the fewest historical Metrics required.
            Unlike Statistical, a median and MAD are mathematically
            defined even for a single value (everything collapses to
            that point) — the default of 2 is a judgment call that one
            historical point is too thin an "everyday" to compare
            against, not a hard mathematical floor.
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
