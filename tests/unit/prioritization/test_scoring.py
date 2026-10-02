from __future__ import annotations

import pytest

from sentinel.domain import Criticality, Severity, Status
from sentinel.domain.incident import IncidentScoreComponents
from sentinel.prioritization import scoring
from sentinel.prioritization.config import ScoreWeights
from sentinel.prioritization.frequency import summarize

# -- severity_score / criticality_score --------------------------------------


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (Severity.INFO, 10.0),
        (Severity.WARNING, 40.0),
        (Severity.HIGH, 70.0),
        (Severity.CRITICAL, 100.0),
    ],
)
def test_severity_score_is_monotonic_across_the_four_tiers(
    severity: Severity, expected: float
) -> None:
    assert scoring.severity_score(severity) == expected


@pytest.mark.parametrize(
    ("criticality", "expected"),
    [
        (Criticality.LOW, 10.0),
        (Criticality.MEDIUM, 40.0),
        (Criticality.HIGH, 70.0),
        (Criticality.CRITICAL, 100.0),
    ],
)
def test_criticality_score_is_monotonic_across_the_four_tiers(
    criticality: Criticality, expected: float
) -> None:
    assert scoring.criticality_score(criticality) == expected


def test_severity_and_criticality_are_commensurate() -> None:
    """HIGH severity and HIGH criticality score the same."""
    assert scoring.severity_score(Severity.HIGH) == scoring.criticality_score(Criticality.HIGH)


# -- deviation_score ----------------------------------------------------------


def test_deviation_score_zero_ratio_is_zero() -> None:
    assert scoring.deviation_score(0.0) == 0.0


def test_deviation_score_at_the_tolerance_edge_is_half() -> None:
    assert scoring.deviation_score(1.0) == 50.0


def test_deviation_score_saturates_at_twice_the_edge() -> None:
    assert scoring.deviation_score(2.0) == 100.0
    assert scoring.deviation_score(10.0) == 100.0  # extremely large deviation, still capped


def test_deviation_score_unknown_ratio_is_a_documented_moderate_default() -> None:
    """Unknown deviation scores the moderate default."""
    assert scoring.deviation_score(None) == 50.0


def test_deviation_score_is_monotonic_in_ratio() -> None:
    ratios = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0]
    scores = [scoring.deviation_score(r) for r in ratios]
    assert scores == sorted(scores)


# -- frequency_score ------------------------------------------------------


def test_frequency_score_first_occurrence_is_low_regardless_of_anything_else() -> None:
    """A first occurrence always scores low on frequency."""
    history = summarize([Status.PASS] * 50)  # 50 clean runs, this would be the first failure
    assert scoring.frequency_score(history) == 10.0


def test_frequency_score_scales_with_rate() -> None:
    low_rate = summarize([Status.FAIL] + [Status.PASS] * 9)  # 1/10
    high_rate = summarize([Status.FAIL] * 8 + [Status.PASS] * 2)  # 8/10
    assert scoring.frequency_score(low_rate) < scoring.frequency_score(high_rate)


def test_frequency_score_consecutive_bonus_is_capped() -> None:
    """A long streak can't push frequency past 100."""
    persistent = summarize([Status.FAIL] * 200)
    assert scoring.frequency_score(persistent) == 100.0


def test_frequency_score_is_monotonic_in_occurrences_holding_window_fixed() -> None:
    fewer = summarize([Status.FAIL, Status.PASS, Status.PASS, Status.PASS])
    more = summarize([Status.FAIL, Status.FAIL, Status.FAIL, Status.PASS])
    assert scoring.frequency_score(fewer) <= scoring.frequency_score(more)


# -- confidence_score ------------------------------------------------------


def test_confidence_score_scales_zero_to_one_onto_zero_to_one_hundred() -> None:
    assert scoring.confidence_score(0.0) == 0.0
    assert scoring.confidence_score(1.0) == 100.0
    assert scoring.confidence_score(0.5) == 50.0


def test_confidence_score_clamps_out_of_range_input() -> None:
    assert scoring.confidence_score(-0.5) == 0.0
    assert scoring.confidence_score(1.5) == 100.0


# -- aggregate_score ---------------------------------------------------------


def _components(**overrides: float) -> IncidentScoreComponents:
    base = {
        "severity_score": 50.0,
        "criticality_score": 50.0,
        "deviation_score": 50.0,
        "frequency_score": 50.0,
        "confidence_score": 50.0,
    }
    base.update(overrides)
    return IncidentScoreComponents(**base)


_COMPONENT_FIELDS = (
    "severity_score",
    "criticality_score",
    "deviation_score",
    "frequency_score",
    "confidence_score",
)

_EVEN_WEIGHTS = ScoreWeights(
    severity=0.2, criticality=0.2, deviation=0.2, frequency=0.2, confidence=0.2
)


def test_aggregate_score_of_all_fifty_is_fifty_regardless_of_weights() -> None:
    """All components at 50 give 50 for any valid weights."""
    assert scoring.aggregate_score(_components(), ScoreWeights()) == 50.0
    assert scoring.aggregate_score(_components(), _EVEN_WEIGHTS) == 50.0


def test_aggregate_score_is_bounded_zero_to_one_hundred() -> None:
    all_zero = _components(**{field: 0.0 for field in _COMPONENT_FIELDS})
    all_max = _components(**{field: 100.0 for field in _COMPONENT_FIELDS})
    assert scoring.aggregate_score(all_zero, ScoreWeights()) == 0.0
    assert scoring.aggregate_score(all_max, ScoreWeights()) == 100.0


@pytest.mark.parametrize("field_name", _COMPONENT_FIELDS)
def test_aggregate_score_is_monotonic_in_each_component_independently(field_name: str) -> None:
    """Raising one component never lowers the total."""
    weights = ScoreWeights()
    low = scoring.aggregate_score(_components(**{field_name: 10.0}), weights)
    high = scoring.aggregate_score(_components(**{field_name: 90.0}), weights)
    assert high >= low
