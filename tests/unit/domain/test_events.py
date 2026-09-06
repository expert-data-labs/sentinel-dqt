from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from sentinel.domain import (
    Criticality,
    Dataset,
    Metric,
    QualityEvent,
    Severity,
    Status,
    ThresholdResult,
    ValidationRun,
)


def _metric(value: float = 500.0, details: str | None = None) -> Metric:
    return Metric(
        metric_name="row_count", value=value, computed_at=datetime.now(UTC), details=details
    )


def _threshold_result(
    status: Status = Status.FAIL, details: str | None = None
) -> ThresholdResult:
    return ThresholdResult(
        status=status, expected="row_count >= 1000", strategy_type="static", details=details
    )


def _dataset() -> Dataset:
    return Dataset(
        id="orders",
        name="orders",
        source_type="duckdb",
        environment="production",
        owner="data-platform-team",
        criticality=Criticality.HIGH,
    )


def test_quality_event_exposes_flat_view_over_metric_and_threshold_result() -> None:
    metric = _metric(value=500.0)
    threshold_result = _threshold_result(status=Status.FAIL)
    event = QualityEvent(
        severity=Severity.CRITICAL,
        blocking=True,
        metric=metric,
        threshold_result=threshold_result,
    )

    assert event.rule_name == "row_count"
    assert event.actual == 500.0
    assert event.expected == "row_count >= 1000"
    assert event.status is Status.FAIL
    assert event.severity is Severity.CRITICAL
    assert event.blocking is True


def test_quality_event_details_defaults_to_none() -> None:
    event = QualityEvent(
        severity=Severity.WARNING,
        blocking=True,
        metric=_metric(),
        threshold_result=_threshold_result(),
    )
    assert event.details is None


def test_quality_event_details_passes_through_from_its_metric() -> None:
    """Milestone 3: details is a read-only passthrough over Metric.details,
    the same pattern actual/expected/status already use over their own
    underlying fields."""
    event = QualityEvent(
        severity=Severity.WARNING,
        blocking=True,
        metric=_metric(details='{"missing_columns": ["created_at"]}'),
        threshold_result=_threshold_result(),
    )
    assert event.details == '{"missing_columns": ["created_at"]}'


def test_threshold_result_details_defaults_to_none() -> None:
    assert _threshold_result().details is None


def test_quality_event_threshold_details_defaults_to_none() -> None:
    event = QualityEvent(
        severity=Severity.WARNING,
        blocking=True,
        metric=_metric(),
        threshold_result=_threshold_result(),
    )
    assert event.threshold_details is None


def test_quality_event_threshold_details_passes_through_from_its_threshold_result() -> None:
    """Milestone 4: threshold_details mirrors details (Milestone 3) exactly,
    but over ThresholdResult.details instead of Metric.details — the two
    stay distinct properties because they answer different questions (what
    a Rule observed vs. how a ThresholdStrategy judged it), not because
    QualityEvent has grown a special case for either one."""
    baseline_json = '{"baseline": 1000.0, "lower": 900.0, "upper": 1100.0, "n": 30}'
    event = QualityEvent(
        severity=Severity.WARNING,
        blocking=True,
        metric=_metric(),
        threshold_result=_threshold_result(details=baseline_json),
    )
    assert event.threshold_details == baseline_json
    assert event.details is None  # unaffected — a different underlying field


def test_quality_event_is_frozen() -> None:
    event = QualityEvent(
        severity=Severity.INFO,
        blocking=False,
        metric=_metric(),
        threshold_result=_threshold_result(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.severity = Severity.CRITICAL  # type: ignore[misc]


def test_validation_run_holds_its_quality_events() -> None:
    event = QualityEvent(
        severity=Severity.HIGH,
        blocking=True,
        metric=_metric(),
        threshold_result=_threshold_result(),
    )
    started = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 23, 12, 0, 5, tzinfo=UTC)

    run = ValidationRun(
        dataset=_dataset(),
        policy_version="1",
        started_at=started,
        finished_at=finished,
        status=Status.FAIL,
        quality_events=(event,),
    )

    assert run.status is Status.FAIL
    assert run.quality_events == (event,)
    assert run.dataset.id == "orders"


def test_validation_run_is_frozen() -> None:
    run = ValidationRun(
        dataset=_dataset(),
        policy_version="1",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status=Status.PASS,
        quality_events=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        run.status = Status.FAIL  # type: ignore[misc]
