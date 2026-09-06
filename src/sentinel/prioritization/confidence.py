"""Anomaly confidence: how much to trust that a given non-PASS
ThresholdResult reflects a genuine anomaly, rather than noise or a
strategy operating outside its own comfort zone.

Deterministic and explainable by design (no ML model, per the milestone's
explicit constraint) -- a small multiplicative combination of three
factors, each independently documented and each answering a question this
codebase can already answer from information Milestone 4 produced:

    base(strategy_type)              -- does this strategy have a
                                         statistical basis at all, and how
                                         did it hold up in Milestone 4's own
                                         measured experiments?
    sample_size_factor(n_history)    -- how much history backs the
                                         baseline this particular
                                         evaluation used?
    consistency_factor(consecutive)  -- is this failure corroborated by
                                         immediately preceding ones, or a
                                         one-off?

The combination is multiplicative *within this one component only* --
see docs/architecture/0006-milestone-5-design.md Part 7/Part 8 for why the
top-level incident score stays additive across components (deviation,
frequency, criticality, ...) even though confidence itself is built from a
small internal product. Each individual factor here is bounded well away
from zero specifically so a thin-history evaluation is scored as "less
confident," never as "no confidence" (a genuinely different claim this
module has no basis to make).

**Documented limitation** (per the milestone's own instruction to document
insufficiency rather than hide it): for a static threshold, and for any
adaptive strategy evaluated right at its own ``min_history`` floor, there
is little or no statistical basis to be confident about. The constants
below are judgment calls, not derived quantities -- flagged here rather
than dressed up as more principled than they are.
"""

from __future__ import annotations

import json
from typing import Any

from sentinel.domain import ThresholdResult
from sentinel.prioritization.frequency import FailureHistory

# Base confidence per strategy_type, in [0, 1]. static has no statistical
# corroboration at all (a human-declared fixed bound) -- its base reflects
# "we trust the business rule," not "we trust an anomaly-detection model,"
# since there isn't one. The other four bases are informed by Milestone 4's
# own measured, documented confusion-matrix results
# (docs/experiments/milestone-4-results.md), not invented from nothing --
# but four synthetic scenarios is a small sample, so these remain coarse,
# adjustable judgment calls, not statistically derived weights:
#   - seasonal was M4's headline success (~6x fewer false positives than
#     static on the seasonal scenario, with no loss of real-anomaly
#     detection) -- highest base.
#   - median_mad is specifically robust to outlier-contaminated history
#     (catches a repeated outlier statistical misses the second time) --
#     second-highest.
#   - statistical can be "quiet when it shouldn't be" (0 false positives on
#     the seasonal scenario, but at the cost of missing the one real
#     anomaly) -- a real blind spot, not a reason for high confidence when
#     it does fire.
#   - percentage_deviation was M4's own documented worst case on
#     non-stationary data (26 false positives on the seasonal scenario,
#     worse than static) -- lowest of the adaptive strategies.
_STRATEGY_BASE_CONFIDENCE: dict[str, float] = {
    "static": 0.60,
    "percentage_deviation": 0.60,
    "statistical": 0.65,
    "median_mad": 0.75,
    "seasonal": 0.80,
}
_DEFAULT_BASE_CONFIDENCE = 0.50  # an unrecognized strategy_type: no basis to assume more.

# Strategies without a history/sample-size concept -- sample_size_factor is
# a no-op (1.0) for these rather than penalizing them for a question that
# doesn't apply to them.
_STRATEGIES_WITHOUT_SAMPLE_SIZE = frozenset({"static"})

_SAMPLE_SIZE_CAP = 30  # matches the largest per-bucket sample size Milestone 4's
# own synthetic scenarios used; no meaningful confidence gain is claimed beyond it.
_SAMPLE_SIZE_FLOOR = 0.5  # even a thin (but valid, i.e. >= min_history) sample
# gets half credit, not near-zero -- "less confident," never "no confidence."

_CONSISTENCY_STEP = 0.03
_CONSISTENCY_CAP = 1.15  # bounded so a long streak nudges, but never dominates,
# confidence -- historical frequency (a separate scoring component) is where a
# long streak's operational significance is actually meant to be felt.


def compute_confidence(result: ThresholdResult, failure_history: FailureHistory) -> float:
    """A confidence score in [0, 1] for ``result``, given ``failure_history``
    for the same (dataset, rule) pair (sentinel.prioritization.frequency).
    """
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

    # Public: also reused by sentinel.prioritization.prioritizer to explain
    # confidence in an Incident's reasons, so both places agree on which
    # sample size a given strategy_type's confidence was actually based on.
    #
    # seasonal buckets by day_of_week -- n_history_in_bucket is the sample
    # size that actually backed *this* evaluation's baseline, unlike
    # n_history_total (every day of the week combined).
    if "n_history_in_bucket" in details:
        return details["n_history_in_bucket"]
    return details.get("n_history")


def _consistency_factor(consecutive_failures: int) -> float:
    return min(1.0 + _CONSISTENCY_STEP * consecutive_failures, _CONSISTENCY_CAP)
