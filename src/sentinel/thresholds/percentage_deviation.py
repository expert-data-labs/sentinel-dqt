"""PercentageDeviationStrategy: relative change from the mean of recent history."""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from typing import Any, ClassVar

from sentinel.domain import Metric, Status, ThresholdConfig, ThresholdResult
from sentinel.thresholds.base import InsufficientHistoryError, ThresholdConfigError
from sentinel.thresholds.registry import register_threshold_strategy

_DEFAULT_MIN_HISTORY = 1


def _describe_expectation(metric_name: str, baseline: float, max_deviation: float) -> str:
    return f"{metric_name} within ±{max_deviation:.0%} of baseline {baseline:.4g}"


@register_threshold_strategy
class PercentageDeviationStrategy:
    """Pass if ``|actual - baseline| / |baseline| <= max_deviation``.

    ``baseline`` is the mean of history.

    Params:

    - ``max_deviation`` (required), e.g. 0.10 for +/-10%
    - ``min_history`` (default 1)

    Edge cases:

    - baseline 0, actual 0: deviation 0 (PASS)
    - baseline 0, actual non-zero: FAIL with ``deviation: null`` and a note
    - negative baseline: handled by comparing the absolute value
    """

    strategy_type: ClassVar[str] = "percentage_deviation"

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        max_deviation = config.params.get("max_deviation")
        if max_deviation is None:
            raise ThresholdConfigError(
                f"percentage_deviation threshold for {metric.metric_name!r} requires "
                "'max_deviation' in its params"
            )

        min_history = config.params.get("min_history", _DEFAULT_MIN_HISTORY)
        if len(history) < min_history:
            raise InsufficientHistoryError(
                f"percentage_deviation threshold for {metric.metric_name!r} requires at least "
                f"{min_history} historical metric(s), got {len(history)}"
            )

        baseline = statistics.fmean(m.value for m in history)
        actual = metric.value

        deviation: float | None
        if baseline == 0.0:
            deviation = 0.0 if actual == 0.0 else None
        else:
            deviation = (actual - baseline) / baseline

        if deviation is None:
            status = Status.FAIL
            note = "baseline is 0; relative deviation is undefined for a nonzero actual value"
        else:
            status = Status.PASS if abs(deviation) <= max_deviation else Status.FAIL
            note = None

        details: dict[str, Any] = {
            "method": "percentage_deviation",
            "actual": actual,
            "baseline": baseline,
            "deviation": deviation,
            "max_deviation": max_deviation,
            "n_history": len(history),
        }
        if note is not None:
            details["note"] = note

        return ThresholdResult(
            status=status,
            expected=_describe_expectation(metric.metric_name, baseline, max_deviation),
            strategy_type=self.strategy_type,
            details=json.dumps(details),
        )
