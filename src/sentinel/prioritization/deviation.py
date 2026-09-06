"""Deviation magnitude: how far off, in normalized terms, one ThresholdResult
says a Metric's value was.

This is the one place in the codebase that knows each threshold strategy's
own ``details`` JSON shape (percentage_deviation's ``deviation``/
``max_deviation``; statistical/median_mad/seasonal's shared ``lower``/
``upper``; static's ``actual``/``min``/``max``). Deliberately kept here, in
the prioritization package, rather than pushed back into each
ThresholdStrategy -- the milestone's own constraint is "do not put
strategy-specific prioritization logic into individual ThresholdStrategies",
and a single, isolated translator satisfies that without touching five
already-shipped Milestone 4 files. See
docs/architecture/0006-milestone-5-design.md Part 4 for the two designs
considered and why this one was chosen.

Every branch here reduces to the same normalized shape: 0.0 at the
baseline/center, 1.0 exactly at the strategy's own tolerance edge, >1.0
beyond it -- one comparable "how far off" number regardless of which
strategy produced the underlying ThresholdResult, without hardcoding
anything about what a particular metric_name (row_count, null_rate, ...)
means. That's the "metric-aware but generic" approach the milestone brief
asks for: genericity comes from operating on each strategy's own already-
computed tolerance, not from a per-metric-name table.
"""

from __future__ import annotations

import json
from typing import Any

from sentinel.domain import ThresholdResult

# Assigned when a strategy's own math leaves "how far off" mathematically
# undefined -- PercentageDeviationStrategy's baseline == 0 with a nonzero
# actual value, or a static/bound-based tolerance that collapses to a
# zero-width edge. Reporting "no information" here would understate a
# genuine jump-from-nothing as if it were unremarkable, so this is
# deliberately a large, fixed ratio rather than None -- a documented
# judgment call, per the milestone brief's own instruction to document
# rather than hide an indeterminate case. 2.0 is twice "exactly at the
# tolerance edge", already past the point sentinel.prioritization.scoring's
# deviation_score saturates at.
_UNDEFINED_BASELINE_RATIO = 2.0

_BOUND_BASED_STRATEGIES = frozenset({"statistical", "median_mad", "seasonal"})


def compute_deviation_ratio(result: ThresholdResult) -> float | None:
    """A normalized deviation ratio for ``result``, or ``None`` when there
    isn't enough information to compute one -- an unrecognized
    ``strategy_type``, or a strategy that recorded no ``details``.
    ``sentinel.prioritization.scoring`` documents its own explicit default
    for the ``None`` case rather than this function silently guessing one.
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
        # baseline == 0, actual != 0 -- PercentageDeviationStrategy's own
        # docstring documents this as mathematically undefined.
        return _UNDEFINED_BASELINE_RATIO
    if not max_deviation:
        return _UNDEFINED_BASELINE_RATIO
    return abs(deviation) / max_deviation


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
    # Within bounds: static only ever produces PASS or FAIL (never WARN),
    # and IncidentPrioritizer only prioritizes non-PASS events, so this is
    # dead code in practice today -- kept as a defensive, documented
    # default rather than an unreachable assumption.
    return 0.0


def _relative_distance(actual: float, bound: float) -> float:
    if bound == 0:
        return _UNDEFINED_BASELINE_RATIO
    return abs(actual - bound) / abs(bound)


def _bound_based_ratio(details: dict[str, Any]) -> float | None:
    """statistical/median_mad/seasonal all store ``lower``/``upper`` under
    identical keys, and every one of their bounds is symmetric around a
    center (``center +/- multiplier * spread``) -- so the midpoint of
    ``lower``/``upper`` recovers that center without needing to know which
    strategy-specific key (``mean`` vs. ``median``) it was stored under,
    and without needing to know the strategy's own multiplier (``n_sigma``
    vs. ``n_mad``) either. This is what lets one branch serve all three
    bound-based strategies uniformly.
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
    return abs(actual - center) / half_width
