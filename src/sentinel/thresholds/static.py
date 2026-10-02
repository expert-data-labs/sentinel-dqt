"""StaticThresholdStrategy: compare a Metric against a fixed min/max.

Reads only ``min`` and ``max`` from params and works for every rule. Returns
PASS or FAIL (never WARN). ``details`` holds actual/min/max for prioritization.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, ClassVar

from sentinel.domain import Metric, Status, ThresholdConfig, ThresholdResult
from sentinel.thresholds.base import ThresholdConfigError
from sentinel.thresholds.registry import register_threshold_strategy


def _describe_expectation(metric_name: str, min_bound: Any, max_bound: Any) -> str:
    if min_bound is not None and max_bound is not None:
        return f"{min_bound} <= {metric_name} <= {max_bound}"
    if min_bound is not None:
        return f"{metric_name} >= {min_bound}"
    return f"{metric_name} <= {max_bound}"


@register_threshold_strategy
class StaticThresholdStrategy:
    """Pass if the value is within ``min`` and/or ``max`` (inclusive). Ignores
    history.
    """

    strategy_type: ClassVar[str] = "static"

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        min_bound = config.params.get("min")
        max_bound = config.params.get("max")

        if min_bound is None and max_bound is None:
            raise ThresholdConfigError(
                f"static threshold for {metric.metric_name!r} requires "
                "'min' and/or 'max' in its params"
            )

        within_bounds = (min_bound is None or metric.value >= min_bound) and (
            max_bound is None or metric.value <= max_bound
        )

        details: dict[str, Any] = {
            "method": "static",
            "actual": metric.value,
            "min": min_bound,
            "max": max_bound,
        }

        return ThresholdResult(
            status=Status.PASS if within_bounds else Status.FAIL,
            expected=_describe_expectation(metric.metric_name, min_bound, max_bound),
            strategy_type=self.strategy_type,
            details=json.dumps(details),
        )
