"""Deviation ratio: how far a value was from normal, on one common scale.

0.0 = at the baseline/center, 1.0 = exactly at the tolerance edge, >1.0 = beyond
it. This is the only module that reads each strategy's ``details`` JSON, so
strategies stay free of prioritization logic.
"""

from __future__ import annotations

import json
from typing import Any

from sentinel.domain import ThresholdResult

# Used when the ratio is undefined (zero baseline or zero-width tolerance).
# Treated as a large deviation rather than "unknown"; 2.0 = maximum score.
_UNDEFINED_BASELINE_RATIO = 2.0

_BOUND_BASED_STRATEGIES = frozenset({"statistical", "median_mad", "seasonal"})


def compute_deviation_ratio(result: ThresholdResult) -> float | None:
    """Normalized deviation for ``result``, or None for unknown strategies or
    missing details.
    """
    if result.details is None:
        return None

    details: dict[str, Any] = json.loads(result.details)

    if result.strategy_type == "percentage_deviation":
        return _percentage_deviation_ratio(details)
    if result.strategy_type == "static":
        return _static_ratio(details)
    if result.strategy_type in _BOUND_BASED_STRATEGIES:
        return _bound_based_ratio(details)
    return None


def _percentage_deviation_ratio(details: dict[str, Any]) -> float:
    deviation = details.get("deviation")
    max_deviation = details.get("max_deviation")
    if deviation is None:
        # baseline == 0 and actual != 0: undefined.
        return _UNDEFINED_BASELINE_RATIO
    if not max_deviation:
        return _UNDEFINED_BASELINE_RATIO
    return float(abs(deviation) / max_deviation)


def _static_ratio(details: dict[str, Any]) -> float | None:
    actual = details.get("actual")
    min_bound = details.get("min")
    max_bound = details.get("max")
    if actual is None:
        return None

    if min_bound is not None and actual < min_bound:
        return _relative_distance(actual, min_bound)
    if max_bound is not None and actual > max_bound:
        return _relative_distance(actual, max_bound)
    # Within bounds. Not reached today (passing events aren't prioritized).
    return 0.0


def _relative_distance(actual: float, bound: float) -> float:
    if bound == 0:
        return _UNDEFINED_BASELINE_RATIO
    return abs(actual - bound) / abs(bound)


def _bound_based_ratio(details: dict[str, Any]) -> float | None:
    """Ratio for statistical, median_mad and seasonal.

    Their bounds are symmetric, so the midpoint of lower/upper is the center and
    half the width is the tolerance.
    """
    actual = details.get("actual")
    lower = details.get("lower")
    upper = details.get("upper")
    if actual is None or lower is None or upper is None:
        return None

    half_width = (upper - lower) / 2
    center = (upper + lower) / 2
    if half_width == 0:
        return _UNDEFINED_BASELINE_RATIO
    return float(abs(actual - center) / half_width)
