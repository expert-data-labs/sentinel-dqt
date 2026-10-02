from __future__ import annotations

import pytest

from sentinel.domain.incident import IncidentPriority
from sentinel.prioritization.config import (
    DEFAULT_INCIDENT_PRIORITIZATION_CONFIG,
    IncidentPrioritizationConfigError,
    PriorityThresholds,
    ScoreWeights,
)


def test_default_weights_sum_to_one() -> None:
    weights = ScoreWeights()
    total = (
        weights.severity
        + weights.criticality
        + weights.deviation
        + weights.frequency
        + weights.confidence
    )
    assert total == pytest.approx(1.0)


def test_weights_not_summing_to_one_raise() -> None:
    with pytest.raises(IncidentPrioritizationConfigError):
        ScoreWeights(severity=0.5, criticality=0.5, deviation=0.5, frequency=0.0, confidence=0.0)


def test_weights_summing_to_one_via_different_split_is_accepted() -> None:
    ScoreWeights(severity=0.2, criticality=0.2, deviation=0.2, frequency=0.2, confidence=0.2)


def test_default_thresholds_match_the_milestone_briefs_own_example() -> None:
    thresholds = PriorityThresholds()
    assert (thresholds.warning_at, thresholds.high_at, thresholds.critical_at) == (25.0, 50.0, 75.0)


def test_thresholds_not_strictly_increasing_raise() -> None:
    with pytest.raises(IncidentPrioritizationConfigError):
        PriorityThresholds(warning_at=50, high_at=25, critical_at=75)


def test_thresholds_with_equal_cut_points_raise() -> None:
    with pytest.raises(IncidentPrioritizationConfigError):
        PriorityThresholds(warning_at=25, high_at=25, critical_at=75)


# -- priority boundaries --


def test_boundary_just_below_warning_is_info() -> None:
    thresholds = PriorityThresholds()
    assert thresholds.classify(24.9) is IncidentPriority.INFO


def test_boundary_at_warning_is_warning() -> None:
    thresholds = PriorityThresholds()
    assert thresholds.classify(25.0) is IncidentPriority.WARNING


def test_boundary_just_below_high_is_warning() -> None:
    thresholds = PriorityThresholds()
    assert thresholds.classify(49.9) is IncidentPriority.WARNING


def test_boundary_at_high_is_high() -> None:
    thresholds = PriorityThresholds()
    assert thresholds.classify(50.0) is IncidentPriority.HIGH


def test_boundary_just_below_critical_is_high() -> None:
    thresholds = PriorityThresholds()
    assert thresholds.classify(74.9) is IncidentPriority.HIGH


def test_boundary_at_critical_is_critical() -> None:
    thresholds = PriorityThresholds()
    assert thresholds.classify(75.0) is IncidentPriority.CRITICAL


def test_boundary_at_zero_and_one_hundred() -> None:
    thresholds = PriorityThresholds()
    assert thresholds.classify(0.0) is IncidentPriority.INFO
    assert thresholds.classify(100.0) is IncidentPriority.CRITICAL


def test_default_config_uses_default_weights_and_thresholds() -> None:
    assert DEFAULT_INCIDENT_PRIORITIZATION_CONFIG.weights == ScoreWeights()
    assert DEFAULT_INCIDENT_PRIORITIZATION_CONFIG.thresholds == PriorityThresholds()
