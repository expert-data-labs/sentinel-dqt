"""Incident scoring: five 0-100 components combined by a weighted sum.

A weighted sum (rather than a product) keeps the score in 0-100, means raising
one component can only raise the total, and stops one low factor from zeroing
out the rest.
"""

from __future__ import annotations

from sentinel.domain import Criticality, Severity
from sentinel.domain.incident import IncidentScoreComponents
from sentinel.prioritization.config import ScoreWeights
from sentinel.prioritization.frequency import FailureHistory

# Severity and criticality share one scale so they're directly comparable.
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

# A deviation ratio of 1.0 is the tolerance edge; 2x or more scores 100.
_DEVIATION_SATURATION_RATIO = 2.0

# Unknown deviation scores as moderate, neither ignored nor maximal.
_DEVIATION_SCORE_WHEN_UNKNOWN = 50.0

# First occurrences score low. Otherwise: failure rate * 100, plus a capped
# bonus for an ongoing streak of failures.
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
    """Weighted sum of the components, rounded to 1 decimal (0-100)."""
    raw = (
        components.severity_score * weights.severity
        + components.criticality_score * weights.criticality
        + components.deviation_score * weights.deviation
        + components.frequency_score * weights.frequency
        + components.confidence_score * weights.confidence
    )
    return round(raw, 1)
