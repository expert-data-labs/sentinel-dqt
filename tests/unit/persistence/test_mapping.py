from __future__ import annotations

from datetime import UTC, datetime

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
from sentinel.persistence.mapping import to_rows


def _dataset() -> Dataset:
    return Dataset(
        id="orders",
        name="orders",
        source_type="duckdb",
        environment="production",
        owner="data-platform-team",
        criticality=Criticality.HIGH,
        config_reference="data/orders.csv",
    )


def _run() -> ValidationRun:
    started = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 26, 12, 0, 1, tzinfo=UTC)
    metric = Metric(metric_name="row_count", value=12.0, computed_at=finished)
    threshold_result = ThresholdResult(
        status=Status.FAIL, expected="row_count >= 1000", strategy_type="static"
    )
    event = QualityEvent(
        severity=Severity.WARNING, blocking=True, metric=metric, threshold_result=threshold_result
    )
    return ValidationRun(
        dataset=_dataset(),
        policy_version="unversioned",
        started_at=started,
        finished_at=finished,
        status=Status.FAIL,
        quality_events=(event,),
    )


def test_to_rows_maps_the_dataset_fields_from_run_dataset() -> None:
    persistable = to_rows(_run())

    assert persistable.dataset.id == "orders"
    assert persistable.dataset.source_type == "duckdb"
    assert persistable.dataset.criticality == "high"
    assert persistable.dataset.config_reference == "data/orders.csv"


def test_to_rows_maps_the_run_fields() -> None:
    run = _run()
    persistable = to_rows(run)

    assert persistable.run.dataset_id == "orders"
    assert persistable.run.policy_version == "unversioned"
    assert persistable.run.status == "fail"
    assert persistable.run.started_at == run.started_at
    assert persistable.run.finished_at == run.finished_at


def test_to_rows_generates_a_fresh_run_id_each_call() -> None:
    run = _run()
    first = to_rows(run)
    second = to_rows(run)
    assert first.run.id != second.run.id


def test_to_rows_maps_one_metric_and_event_per_quality_event() -> None:
    persistable = to_rows(_run())

    assert len(persistable.metrics) == 1
    assert len(persistable.events) == 1

    metric_row = persistable.metrics[0]
    event_row = persistable.events[0]

    assert metric_row.metric_name == "row_count"
    assert metric_row.value == 12.0
    assert metric_row.validation_run_id == persistable.run.id

    assert event_row.metric_id == metric_row.id
    assert event_row.validation_run_id == persistable.run.id
    assert event_row.status == "fail"
    assert event_row.expected == "row_count >= 1000"
    assert event_row.strategy_type == "static"
    assert event_row.severity == "warning"
    assert event_row.blocking is True


def test_to_rows_with_no_quality_events_gives_empty_metric_and_event_tuples() -> None:
    run = ValidationRun(
        dataset=_dataset(),
        policy_version="unversioned",
        started_at=datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 8, 26, 12, 0, 1, tzinfo=UTC),
        status=Status.PASS,
        quality_events=(),
    )
    persistable = to_rows(run)

    assert persistable.metrics == ()
    assert persistable.events == ()
