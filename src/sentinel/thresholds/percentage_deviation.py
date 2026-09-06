"""PercentageDeviationStrategy: judge a Metric by how far it deviates,
in relative terms, from the mean of its own recent history.

The first adaptive strategy (Milestone 4): unlike StaticThresholdStrategy,
this one is meaningless without ``history`` — there's no fixed bound to
fall back on, only "how different is this from what's normal for this
rule lately." See docs/architecture/0005-milestone-4-design.md Part 3 for
why the baseline is defined as the *mean* of history rather than the
single most recent value: it's deterministic, uses more than one point of
evidence, and gives ``min_history`` something real to guard.
"""

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
    """Judges a Metric by ``|actual - baseline| / |baseline| <= max_deviation``,
    where ``baseline`` is the mean of the historical Metrics supplied.

    ``config.params``:
        max_deviation (required): the largest acceptable relative
            deviation from baseline, e.g. ``0.10`` for +/-10%.
        min_history (default 1): the fewest historical Metrics required
            before a baseline is trusted. Any positive value works
            mathematically (even a single historical point has a mean),
            but a caller declaring a higher floor is saying "don't judge
            me against a baseline built from just one or two runs."

    Edge cases (docs/architecture/0005-milestone-4-design.md Part 6):
        baseline == 0 and actual == 0: deviation is defined as 0.0 (PASS)
            — a value that hasn't moved from an all-zero baseline hasn't
            deviated, degenerate as that baseline is.
        baseline == 0 and actual != 0: deviation is mathematically
            undefined (division by zero) — any nonzero value is an
            infinite relative change from a zero baseline. Rather than
            raising (which would stop a whole validation run over one
            rule) or silently passing (which would hide a real jump from
            0 to something), this strategy reports FAIL with
            ``details.deviation`` set to ``null`` and an explanation, so
            the event is visible without pretending a percentage exists.
        Negative baselines: the deviation formula
            ``(actual - baseline) / baseline`` is sign-correct as long as
            the comparison uses its absolute value, which is what this
            strategy does — no separate case is needed for a negative
            baseline.
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
