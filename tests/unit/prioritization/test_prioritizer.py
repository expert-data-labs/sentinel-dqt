"""IncidentPrioritizer end to end: seven scenarios, explainability, and the PASS
guard.

Individual components are tested in the other prioritization test files.
Expected ranges were verified by running the prioritizer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from sentinel.domain import (
    Criticality,
    Dataset,
    Metric,
    QualityEvent,
    Severity,
    Status,
    ThresholdResult,
)
from sentinel.domain.incident import IncidentPriority
from sentinel.prioritization.prioritizer import IncidentPrioritizer


def _dataset(criticality: Criticality) -> Dataset:
    return Dataset(
        id="ds",
        name="ds",
        source_type="duckdb",
        environment="prod",
        owner="j",
        criticality=criticality,
    )


def _bound_details(
    actual: float, n_history: int, lower: float = 900, upper: float = 1100
) -> dict[str, Any]:
    """Details dict with lower/upper, as statistical/median_mad/seasonal store
    them.
    """
    return {"actual": actual, "lower": lower, "upper": upper, "n_history": n_history}


def _event(
    severity: Severity,
    strategy_type: str,
    details: dict[str, Any],
    status: Status = Status.FAIL,
) -> QualityEvent:
    metric = Metric(
        metric_name="rule", value=details.get("actual", 0.0), computed_at=datetime.now(UTC)
    )
    threshold_result = ThresholdResult(
        status=status, expected="n/a", strategy_type=strategy_type, details=json.dumps(details)
    )
    return QualityEvent(
        severity=severity, blocking=True, metric=metric, threshold_result=threshold_result
    )


@pytest.fixture
def prioritizer() -> IncidentPrioritizer:
    return IncidentPrioritizer()


def test_scenario_1_small_anomaly_low_criticality(prioritizer: IncidentPrioritizer) -> None:
    """Small deviation, rare occurrence, low dataset criticality, moderate
    confidence -> INFO or WARNING."""
    details = {
        "deviation": 0.03,
        "max_deviation": 0.10,
        "actual": 1030,
        "baseline": 1000,
        "n_history": 5,
    }
    event = _event(Severity.WARNING, "percentage_deviation", details)
    incident = prioritizer.prioritize(_dataset(Criticality.LOW), event, [Status.PASS] * 10)
    assert incident.priority in {IncidentPriority.INFO, IncidentPriority.WARNING}


def test_scenario_2_large_anomaly_low_criticality(prioritizer: IncidentPrioritizer) -> None:
    """Large deviation, rare occurrence, low dataset criticality, high
    confidence -> WARNING or HIGH."""
    event = _event(Severity.WARNING, "median_mad", _bound_details(actual=2000, n_history=40))
    incident = prioritizer.prioritize(_dataset(Criticality.LOW), event, [Status.PASS] * 10)
    assert incident.priority in {IncidentPriority.WARNING, IncidentPriority.HIGH}


def test_scenario_3_moderate_anomaly_critical_dataset(prioritizer: IncidentPrioritizer) -> None:
    """Moderate deviation, rare occurrence, CRITICAL dataset, high
    confidence -> HIGH or CRITICAL."""
    event = _event(Severity.WARNING, "median_mad", _bound_details(actual=1150, n_history=40))
    incident = prioritizer.prioritize(_dataset(Criticality.CRITICAL), event, [Status.PASS] * 10)
    assert incident.priority in {IncidentPriority.HIGH, IncidentPriority.CRITICAL}


def test_scenario_4_repeated_anomaly(prioritizer: IncidentPrioritizer) -> None:
    """Moderate deviation, frequent historical failures, high dataset
    criticality, high confidence -> HIGH or CRITICAL."""
    event = _event(Severity.WARNING, "median_mad", _bound_details(actual=1150, n_history=40))
    outcomes = [Status.FAIL] * 8 + [Status.PASS] * 2
    incident = prioritizer.prioritize(_dataset(Criticality.HIGH), event, outcomes)
    assert incident.priority in {IncidentPriority.HIGH, IncidentPriority.CRITICAL}


def test_scenario_5_false_positive_prone_anomaly_is_not_over_escalated(
    prioritizer: IncidentPrioritizer,
) -> None:
    """A small deviation on thin history must not reach HIGH or CRITICAL."""
    event = _event(Severity.WARNING, "statistical", _bound_details(actual=1005, n_history=2))
    incident = prioritizer.prioritize(_dataset(Criticality.MEDIUM), event, [Status.PASS] * 3)
    assert incident.priority in {IncidentPriority.INFO, IncidentPriority.WARNING}
    assert incident.components.deviation_score < 20.0  # the actual value barely moved


def test_scenario_6_extreme_failure_is_critical(prioritizer: IncidentPrioritizer) -> None:
    """Severe validation failure, very large deviation, frequent failure,
    critical dataset, very high confidence -> CRITICAL."""
    details = {
        "actual": 5000,
        "lower": 900,
        "upper": 1100,
        "n_history_in_bucket": 40,
        "n_history_total": 200,
    }
    event = _event(Severity.CRITICAL, "seasonal", details)
    incident = prioritizer.prioritize(_dataset(Criticality.CRITICAL), event, [Status.FAIL] * 20)
    assert incident.priority is IncidentPriority.CRITICAL


def test_scenario_7_first_occurrence_does_not_inflate_frequency_score(
    prioritizer: IncidentPrioritizer,
) -> None:
    """A first failure after 50 clean runs scores low on frequency."""
    event = _event(Severity.HIGH, "statistical", _bound_details(actual=1150, n_history=30))
    incident = prioritizer.prioritize(_dataset(Criticality.HIGH), event, [Status.PASS] * 50)
    assert incident.components.frequency_score == 10.0


# -- defensive contract -------------------------------------------------------


def test_prioritize_raises_for_a_pass_event(prioritizer: IncidentPrioritizer) -> None:
    details = {"actual": 5, "min": 1, "max": None}
    event = _event(Severity.WARNING, "static", details, status=Status.PASS)
    with pytest.raises(ValueError, match="PASS"):
        prioritizer.prioritize(_dataset(Criticality.MEDIUM), event, [])


# -- explainability ---------------------------------------------------------


def test_incident_reasons_mention_criticality_severity_deviation_frequency_confidence(
    prioritizer: IncidentPrioritizer,
) -> None:
    event = _event(Severity.HIGH, "median_mad", _bound_details(actual=1150, n_history=40))
    incident = prioritizer.prioritize(_dataset(Criticality.CRITICAL), event, [Status.FAIL] * 3)

    joined = " | ".join(incident.reasons)
    assert "criticality" in joined.lower()
    assert "severity" in joined.lower()
    assert "deviation" in joined.lower()
    assert "frequency" in joined.lower()
    assert "confidence" in joined.lower()
    # Reasons come from the Incident's own components.
    assert len(incident.reasons) == 5
