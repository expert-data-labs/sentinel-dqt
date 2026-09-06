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
