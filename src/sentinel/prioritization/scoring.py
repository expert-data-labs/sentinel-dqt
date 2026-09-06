"""The incident scoring model: turns the five raw inputs (severity,
criticality, deviation ratio, failure history, confidence) into
IncidentScoreComponents (each 0-100), then combines them into one final
0-100 score via a weighted additive sum.

**Why weighted additive, not multiplicative or hybrid** (see
docs/architecture/0006-milestone-5-design.md Part 8 for the full
comparison): a product of five factors means one weak factor -- e.g. low
confidence on a first occurrence -- collapses the *entire* score toward
zero regardless of how severe or how critical everything else is, which is
exactly the "surprising amplification/suppression" the milestone brief
warns against, and makes monotonicity fragile (whether raising one factor
raises the product depends on every other factor's current value). A
weighted sum with weights summing to 1.0 is bounded automatically (no
clamping logic needed), monotonic by construction (each component's
contribution is ``weight * component_score``, so raising one component
while holding the rest fixed can only raise the total), and every
component is independently testable with no interaction effects to reason
about.

Each ``*_score`` function below is pure and independently unit-testable,
per the milestone brief's own Part 14 requirement.
"""

from __future__ import annotations

from sentinel.domain import Criticality, Severity
from sentinel.domain.incident import IncidentScoreComponents
from sentinel.prioritization.config import ScoreWeights
from sentinel.prioritization.frequency import FailureHistory

# Severity and Criticality are deliberately scored on the same 4-tier,
# evenly-spaced scale (10/40/70/100) -- not because the two concepts are
# the same (they aren't; see Criticality's own docstring), but so they're
# *commensurate* as inputs to one weighted sum: a HIGH severity rule and a
# HIGH criticality dataset contribute the same amount, which is what makes
# "HIGH severity on a LOW criticality dataset" vs. "MODERATE severity on a
# CRITICAL dataset" genuinely comparable (the milestone brief's own
# worked example) rather than arbitrarily weighted against each other by
# an accident of scale choice.
_SEVERITY_SCORES: dict[Severity, float] = {
    Severity.INFO: 10.0,
    Severity.WARNING: 40.0,
    Severity.HIGH: 70.0,
    Severity.CRITICAL: 100.0,
}

_CRITICALITY_SCORES: dict[Criticality, float] = {
    Criticality.LOW: 10.0,
    Criticality.MEDIUM: 40.0,
    Criticality.HIGH: 70.0,
    Criticality.CRITICAL: 100.0,
}

# deviation_ratio's own normalized scale already puts 1.0 at "exactly the
# tolerance edge" (see sentinel.prioritization.deviation). Anything at or
# beyond 2x the tolerance edge is scored as maximally deviant -- a
# deliberate saturation point, not a claim that a 10x-over-threshold
# reading is meaningfully "more deviant" than a 2x-over-threshold one for
# prioritization purposes; both are already clearly bad.
_DEVIATION_SATURATION_RATIO = 2.0

# When deviation_ratio is unavailable (an unrecognized strategy_type, or a
# strategy that recorded no details -- see compute_deviation_ratio's own
# ``None`` contract), score it as moderate rather than assuming "no
# deviation" (which would under-escalate) or "maximal deviation" (which
# would over-escalate on missing information alone). A documented default,
# per the milestone brief's own instruction for this exact situation.
_DEVIATION_SCORE_WHEN_UNKNOWN = 50.0

# Historical frequency: a first occurrence is deliberately scored low
# regardless of any other input (Scenario 7 in the milestone brief) --
# there is no history to call "frequent" yet. Otherwise, frequency_rate
# (already in [0, 1]) maps directly to 0-100, plus a bounded bonus for an
# ongoing consecutive streak so a currently-active run of failures scores
# higher than the same overall rate spread sparsely across a long window.
_FIRST_OCCURRENCE_SCORE = 10.0
_CONSECUTIVE_BONUS_PER_FAILURE = 5.0
_CONSECUTIVE_BONUS_CAP = 30.0


def severity_score(severity: Severity) -> float:
    return _SEVERITY_SCORES[severity]


def criticality_score(criticality: Criticality) -> float:
    return _CRITICALITY_SCORES[criticality]


def deviation_score(deviation_ratio: float | None) -> float:
    if deviation_ratio is None:
        return _DEVIATION_SCORE_WHEN_UNKNOWN
    capped = min(max(deviation_ratio, 0.0), _DEVIATION_SATURATION_RATIO)
    return (capped / _DEVIATION_SATURATION_RATIO) * 100.0


def frequency_score(history: FailureHistory) -> float:
    if history.is_first_occurrence:
        return _FIRST_OCCURRENCE_SCORE

    rate_component = history.frequency_rate * 100.0
    consecutive_bonus = min(
        history.consecutive_failures * _CONSECUTIVE_BONUS_PER_FAILURE, _CONSECUTIVE_BONUS_CAP
    )
    return min(rate_component + consecutive_bonus, 100.0)


def confidence_score(confidence: float) -> float:
    return min(max(confidence, 0.0), 1.0) * 100.0


def aggregate_score(components: IncidentScoreComponents, weights: ScoreWeights) -> float:
    """The final 0-100 incident score: a weighted sum of ``components``.
    Bounded to [0, 100] automatically as long as every component is itself
    in [0, 100] and ``weights`` sums to 1.0 (enforced by ScoreWeights's own
    validation) -- no clamping needed here.
    """
    raw = (
        components.severity_score * weights.severity
        + components.criticality_score * weights.criticality
        + components.deviation_score * weights.deviation
        + components.frequency_score * weights.frequency
        + components.confidence_score * weights.confidence
    )
    return round(raw, 1)
