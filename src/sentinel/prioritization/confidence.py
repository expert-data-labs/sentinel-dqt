"""Anomaly confidence: how much to trust that a failure is a real anomaly.

Deterministic, no ML. Three factors multiplied together:

- base: per strategy type
- sample size: how much history backed the baseline
- consistency: whether recent runs also failed

Each factor stays well above zero, so thin history lowers confidence but never
removes it. The constants are judgment calls.
"""

from __future__ import annotations

import json
from typing import Any

from sentinel.domain import ThresholdResult
from sentinel.prioritization.frequency import FailureHistory

# Base confidence per strategy, informed by the threshold strategy
# evaluation (docs/experiments/threshold-strategy-evaluation.md):
#   seasonal - fewest false positives on seasonal data
#   median_mad - robust to outliers in history
#   statistical - can miss real anomalies
#   percentage_deviation - most false positives on seasonal data
#   static - a fixed business rule, no statistical basis
_STRATEGY_BASE_CONFIDENCE: dict[str, float] = {
    "static": 0.60,
    "percentage_deviation": 0.60,
    "statistical": 0.65,
    "median_mad": 0.75,
    "seasonal": 0.80,
}
_DEFAULT_BASE_CONFIDENCE = 0.50  # an unrecognized strategy_type: no basis to assume more.

# Strategies that don't use history: sample size factor is always 1.0.
_STRATEGIES_WITHOUT_SAMPLE_SIZE = frozenset({"static"})

_SAMPLE_SIZE_CAP = 30  # no extra confidence beyond 30 data points
_SAMPLE_SIZE_FLOOR = 0.5  # a thin but valid sample still gets half credit

_CONSISTENCY_STEP = 0.03
_CONSISTENCY_CAP = 1.15  # a streak nudges confidence; frequency scoring does the rest


def compute_confidence(result: ThresholdResult, failure_history: FailureHistory) -> float:
    """Confidence in [0, 1] for ``result``, given the rule's failure history."""
    base = _STRATEGY_BASE_CONFIDENCE.get(result.strategy_type, _DEFAULT_BASE_CONFIDENCE)
    sample_size = _sample_size_factor(result)
    consistency = _consistency_factor(failure_history.consecutive_failures)

    return max(0.0, min(1.0, base * sample_size * consistency))


def _sample_size_factor(result: ThresholdResult) -> float:
    if result.strategy_type in _STRATEGIES_WITHOUT_SAMPLE_SIZE:
        return 1.0

    n_history = extract_n_history(result)
    if n_history is None:
        return _SAMPLE_SIZE_FLOOR

    fraction = min(max(n_history, 0), _SAMPLE_SIZE_CAP) / _SAMPLE_SIZE_CAP
    return _SAMPLE_SIZE_FLOOR + (1.0 - _SAMPLE_SIZE_FLOOR) * fraction


def extract_n_history(result: ThresholdResult) -> int | None:
    if result.details is None:
        return None
    details: dict[str, Any] = json.loads(result.details)

    # Also used by the prioritizer's reasons. For seasonal, use the count
    # within the matching weekday.
    if "n_history_in_bucket" in details:
        raw = details["n_history_in_bucket"]
    else:
        raw = details.get("n_history")
    return None if raw is None else int(raw)


def _consistency_factor(consecutive_failures: int) -> float:
    return min(1.0 + _CONSISTENCY_STEP * consecutive_failures, _CONSISTENCY_CAP)
