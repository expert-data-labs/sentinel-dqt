from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb

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
from sentinel.domain.incident import Incident, IncidentPriority, IncidentScoreComponents
from sentinel.persistence.engine import get_connection
from sentinel.persistence.schema import ensure_schema
from sentinel.persistence.writer import persist_validation_run


def _dataset(owner: str = "data-platform-team") -> Dataset:
    return Dataset(
        id="orders",
        name="orders",
        source_type="duckdb",
        environment="production",
        owner=owner,
        criticality=Criticality.HIGH,
        config_reference="data/orders.csv",
    )


def _run(dataset: Dataset | None = None) -> ValidationRun:
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
        dataset=dataset or _dataset(),
        policy_version="unversioned",
        started_at=started,
        finished_at=finished,
        status=Status.FAIL,
        quality_events=(event,),
    )


def _conn(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    conn = get_connection(tmp_path / "test.duckdb")
    ensure_schema(conn)
    return conn


def test_persist_writes_the_dataset_run_metric_and_event_rows(tmp_path: Path) -> None:
    conn = _conn(tmp_path)

    run_id = persist_validation_run(conn, _run())

    dataset_row = conn.execute("SELECT id, owner FROM datasets WHERE id = 'orders'").fetchone()
    assert dataset_row == ("orders", "data-platform-team")

    run_row = conn.execute(
        "SELECT dataset_id, policy_version, status FROM validation_runs WHERE id = ?", [run_id]
    ).fetchone()
    assert run_row == ("orders", "unversioned", "fail")

    metric_rows = conn.execute(
        "SELECT metric_name, value FROM metrics WHERE validation_run_id = ?", [run_id]
    ).fetchall()
    assert metric_rows == [("row_count", 12.0)]

    event_rows = conn.execute(
        "SELECT status, expected, blocking FROM quality_events WHERE validation_run_id = ?",
        [run_id],
    ).fetchall()
    assert event_rows == [("fail", "row_count >= 1000", True)]


def test_persist_returns_the_generated_run_id(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    run_id = persist_validation_run(conn, _run())

    count = conn.execute("SELECT count(*) FROM validation_runs WHERE id = ?", [run_id]).fetchone()
    assert count == (1,)


def test_persist_upserts_the_dataset_row_on_a_second_run(tmp_path: Path) -> None:
    conn = _conn(tmp_path)

    persist_validation_run(conn, _run(_dataset(owner="alice")))
    persist_validation_run(conn, _run(_dataset(owner="bob")))

    rows = conn.execute("SELECT owner FROM datasets WHERE id = 'orders'").fetchall()
    assert rows == [("bob",)]  # one row, refreshed to the latest owner — not duplicated


def test_persist_two_runs_for_the_same_dataset_creates_two_run_rows(tmp_path: Path) -> None:
    conn = _conn(tmp_path)

    persist_validation_run(conn, _run())
    persist_validation_run(conn, _run())

    count = conn.execute(
        "SELECT count(*) FROM validation_runs WHERE dataset_id = 'orders'"
    ).fetchone()
    assert count == (2,)


# -- incidents and quality_events.details --


def _components() -> IncidentScoreComponents:
    return IncidentScoreComponents(
        severity_score=70.0,
        criticality_score=70.0,
        deviation_score=50.0,
        frequency_score=10.0,
        confidence_score=60.0,
    )


def _run_with_incident(dataset: Dataset | None = None) -> ValidationRun:
    """Like ``_run()`` but with threshold details and one Incident."""
    started = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 26, 12, 0, 1, tzinfo=UTC)
    metric = Metric(metric_name="row_count", value=12.0, computed_at=finished)
    threshold_result = ThresholdResult(
        status=Status.FAIL,
        expected="row_count >= 1000",
        strategy_type="static",
        details='{"method": "static", "actual": 12.0, "min": 1000, "max": null}',
    )
    event = QualityEvent(
        severity=Severity.WARNING, blocking=True, metric=metric, threshold_result=threshold_result
    )
    incident = Incident(
        quality_event=event,
        priority=IncidentPriority.HIGH,
        score=61.0,
        components=_components(),
        reasons=("Dataset criticality: HIGH", "Validation severity: WARNING"),
    )
    return ValidationRun(
        dataset=dataset or _dataset(),
        policy_version="unversioned",
        started_at=started,
        finished_at=finished,
        status=Status.FAIL,
        quality_events=(event,),
        incidents=(incident,),
    )


def test_persist_writes_the_quality_event_details_column(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    run_id = persist_validation_run(conn, _run_with_incident())

    details = conn.execute(
        "SELECT details FROM quality_events WHERE validation_run_id = ?", [run_id]
    ).fetchone()
    assert details == ('{"method": "static", "actual": 12.0, "min": 1000, "max": null}',)


def test_persist_writes_a_null_details_when_the_threshold_result_has_none(
    tmp_path: Path,
) -> None:
    """No threshold details are stored as NULL."""
    conn = _conn(tmp_path)
    run_id = persist_validation_run(conn, _run())

    details = conn.execute(
        "SELECT details FROM quality_events WHERE validation_run_id = ?", [run_id]
    ).fetchone()
    assert details == (None,)


def test_persist_writes_one_incident_row_per_incident(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    run_id = persist_validation_run(conn, _run_with_incident())

    rows = conn.execute(
        "SELECT priority, score FROM incidents WHERE validation_run_id = ?", [run_id]
    ).fetchall()
    assert rows == [("high", 61.0)]


def test_persist_writes_no_incident_rows_when_the_run_has_none(tmp_path: Path) -> None:
    """A run without incidents writes no incident rows."""
    conn = _conn(tmp_path)
    run_id = persist_validation_run(conn, _run())

    count = conn.execute(
        "SELECT count(*) FROM incidents WHERE validation_run_id = ?", [run_id]
    ).fetchone()
    assert count == (0,)


def test_persist_links_an_incident_to_its_own_quality_event_not_another(
    tmp_path: Path,
) -> None:
    """With two failed events, each incident links to its own event."""
    conn = _conn(tmp_path)
    started = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 26, 12, 0, 1, tzinfo=UTC)

    metric_a = Metric(metric_name="row_count", value=12.0, computed_at=finished)
    result_a = ThresholdResult(
        status=Status.FAIL, expected="row_count >= 1000", strategy_type="static"
    )
    event_a = QualityEvent(
        severity=Severity.WARNING, blocking=True, metric=metric_a, threshold_result=result_a
    )

    metric_b = Metric(metric_name="null_rate", value=0.5, computed_at=finished)
    result_b = ThresholdResult(
        status=Status.FAIL, expected="null_rate <= 0.1", strategy_type="static"
    )
    event_b = QualityEvent(
        severity=Severity.HIGH, blocking=True, metric=metric_b, threshold_result=result_b
    )

    incident_b = Incident(
        quality_event=event_b,
        priority=IncidentPriority.CRITICAL,
        score=90.0,
        components=_components(),
        reasons=("Dataset criticality: HIGH",),
    )
    run = ValidationRun(
        dataset=_dataset(),
        policy_version="unversioned",
        started_at=started,
        finished_at=finished,
        status=Status.FAIL,
        quality_events=(event_a, event_b),
        incidents=(incident_b,),
    )

    run_id = persist_validation_run(conn, run)

    linked = conn.execute(
        """
        SELECT qe.status, m.metric_name
        FROM incidents i
        JOIN quality_events qe ON qe.id = i.quality_event_id
        JOIN metrics m ON m.id = qe.metric_id
        WHERE i.validation_run_id = ?
        """,
        [run_id],
    ).fetchone()
    assert linked == ("fail", "null_rate")  # event_b, not event_a
