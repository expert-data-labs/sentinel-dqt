"""StaticThresholdStrategy: judge a Metric against a fixed min/max/range.

Deliberately generic and deliberately thin — it reads exactly two keys
from ``config.params`` (``min``, ``max``) and knows nothing about which
Rule produced the Metric it's judging. Any rule-specific bound (a
"max_duplicates", a "max_delay_minutes") is the wrong param name for this
strategy on purpose: the value of a generic static engine is that every
rule type can share it unmodified, and the moment it starts special-casing
one rule's vocabulary is the moment that stops being true. A rule whose
threshold doesn't fit min/max/range needs a different strategy_type, not a
new param alias here.

Only ever produces Status.PASS or Status.FAIL. Status.WARN stays a valid
value on ThresholdResult, but nothing about a fixed bound has a "soft"
middle band to justify it — that's reserved for an adaptive strategy
(Milestone 4) with an actual two-tier concept of acceptable.

``details`` (Milestone 5): unlike Milestone 4's adaptive strategies, this
strategy had no structured ``details`` until now — there was nothing an
in-memory bound needed to explain beyond the ``expected`` string. Incident
prioritization (sentinel.prioritization.deviation) needs a machine-readable
``actual``/``min``/``max`` to compute a normalized deviation magnitude
uniformly across every strategy_type, the same way it already reads the
adaptive strategies' own ``details``. This is purely additive: the field
was already optional and defaulted to ``None`` on ThresholdResult since
Milestone 4, so no existing caller or test that ignores ``details`` is
affected.
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
    """Judges a Metric against a fixed ``min``, ``max``, or both (a range).

    Both bounds are inclusive: ``min: 10, max: 100`` passes for any value
    in ``[10, 100]``. ``history`` is accepted (per the ThresholdStrategy
    Protocol) and ignored — a static strategy has nothing to compare
    against but the configured bound itself.
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
