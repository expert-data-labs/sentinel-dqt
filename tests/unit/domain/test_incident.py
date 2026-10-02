from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from sentinel.domain import Metric, QualityEvent, Severity, Status, ThresholdResult
from sentinel.domain.incident import Incident, IncidentPriority, IncidentScoreComponents


def _quality_event(status: Status = Status.FAIL) -> QualityEvent:
    metric = Metric(metric_name="row_count", value=500.0, computed_at=datetime.now(UTC))
    threshold_result = ThresholdResult(
        status=status, expected="row_count >= 1000", strategy_type="static"
    )
    return QualityEvent(
        severity=Severity.HIGH, blocking=True, metric=metric, threshold_result=threshold_result
    )


def _components() -> IncidentScoreComponents:
    return IncidentScoreComponents(
        severity_score=70.0,
        criticality_score=70.0,
        deviation_score=50.0,
        frequency_score=10.0,
        confidence_score=60.0,
    )


def test_incident_priority_has_the_four_expected_values() -> None:
    assert {p.value for p in IncidentPriority} == {"info", "warning", "high", "critical"}


def test_incident_priority_is_a_distinct_type_from_severity_and_criticality() -> None:
    """IncidentPriority is its own class.

    Values compare equal as strings at runtime (StrEnum); the separation is for
    the type checker.
    """
    assert not issubclass(IncidentPriority, Severity)
    assert not issubclass(Severity, IncidentPriority)
    assert IncidentPriority.HIGH.__class__ is IncidentPriority
    assert Severity.HIGH.__class__ is Severity


def test_incident_holds_a_reference_to_its_quality_event_not_a_copy() -> None:
    event = _quality_event()
    incident = Incident(
        quality_event=event,
        priority=IncidentPriority.HIGH,
        score=61.0,
        components=_components(),
        reasons=("Dataset criticality: HIGH",),
    )
    assert incident.quality_event is event


def test_incident_is_frozen() -> None:
    event = _quality_event()
    incident = Incident(
        quality_event=event,
        priority=IncidentPriority.HIGH,
        score=61.0,
        components=_components(),
        reasons=(),
    )
    with pytest.raises(FrozenInstanceError):
        incident.score = 100.0  # type: ignore[misc]


def test_incident_score_components_is_frozen() -> None:
    components = _components()
    with pytest.raises(FrozenInstanceError):
        components.severity_score = 0.0  # type: ignore[misc]
