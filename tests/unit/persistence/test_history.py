"""DuckDBHistoricalMetricsSource against a real temp DuckDB store."""

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
from sentinel.persistence.history import DuckDBHistoricalMetricsSource
from sentinel.persistence.schema import ensure_schema
from sentinel.persistence.writer import persist_validation_run


def _dataset(dataset_id: str = "orders") -> Dataset:
    return Dataset(
        id=dataset_id,
        name=dataset_id,
        source_type="duckdb",
        environment="production",
        owner="data-platform-team",
        criticality=Criticality.HIGH,
        config_reference="data/orders.csv",
    )


def _seed_metric(
    conn: duckdb.DuckDBPyConnection,
    *,
    dataset_id: str = "orders",
    metric_name: str = "row_count",
    value: float,
    computed_at: datetime,
) -> None:
    """Save one run whose only event wraps ``metric``."""
    metric = Metric(metric_name=metric_name, value=value, computed_at=computed_at)
    threshold_result = ThresholdResult(status=Status.PASS, expected="n/a", strategy_type="static")
    event = QualityEvent(
        severity=Severity.WARNING, blocking=True, metric=metric, threshold_result=threshold_result
    )
    run = ValidationRun(
        dataset=_dataset(dataset_id),
        policy_version="unversioned",
        started_at=computed_at,
        finished_at=computed_at,
        status=Status.PASS,
        quality_events=(event,),
    )
    persist_validation_run(conn, run)


def _conn(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    conn = get_connection(tmp_path / "test.duckdb")
    ensure_schema(conn)
    return conn


def test_returns_empty_sequence_when_nothing_is_recorded(tmp_path: Path) -> None:
    source = DuckDBHistoricalMetricsSource(_conn(tmp_path))
    assert source.get_history("orders", "row_count") == ()


def test_returns_matching_metrics_most_recent_first(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    day1 = datetime(2026, 9, 1, tzinfo=UTC)
    day2 = datetime(2026, 9, 2, tzinfo=UTC)
    day3 = datetime(2026, 9, 3, tzinfo=UTC)
    _seed_metric(conn, value=1000.0, computed_at=day1)
    _seed_metric(conn, value=1010.0, computed_at=day2)
    _seed_metric(conn, value=995.0, computed_at=day3)

    history = DuckDBHistoricalMetricsSource(conn).get_history("orders", "row_count")

    assert [m.value for m in history] == [995.0, 1010.0, 1000.0]
    assert [m.computed_at for m in history] == [day3, day2, day1]


def test_ignores_a_different_metric_name_on_the_same_dataset(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    computed_at = datetime(2026, 9, 1, tzinfo=UTC)
    _seed_metric(conn, metric_name="row_count", value=1000.0, computed_at=computed_at)
    _seed_metric(conn, metric_name="null_rate_email", value=0.02, computed_at=computed_at)

    history = DuckDBHistoricalMetricsSource(conn).get_history("orders", "row_count")

    assert [m.value for m in history] == [1000.0]


def test_ignores_the_same_metric_name_on_a_different_dataset(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    computed_at = datetime(2026, 9, 1, tzinfo=UTC)
    _seed_metric(conn, dataset_id="orders", value=1000.0, computed_at=computed_at)
    _seed_metric(conn, dataset_id="shipments", value=5000.0, computed_at=computed_at)

    history = DuckDBHistoricalMetricsSource(conn).get_history("orders", "row_count")

    assert [m.value for m in history] == [1000.0]


def test_limit_caps_how_many_rows_come_back(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    for day in range(1, 6):
        _seed_metric(conn, value=float(day), computed_at=datetime(2026, 9, day, tzinfo=UTC))

    history = DuckDBHistoricalMetricsSource(conn, limit=2).get_history("orders", "row_count")

    assert [m.value for m in history] == [5.0, 4.0]


def test_reconstructed_metric_carries_the_requested_metric_name_and_no_details(
    tmp_path: Path,
) -> None:
    conn = _conn(tmp_path)
    computed_at = datetime(2026, 9, 1, tzinfo=UTC)
    _seed_metric(conn, value=1000.0, computed_at=computed_at)

    (metric,) = DuckDBHistoricalMetricsSource(conn).get_history("orders", "row_count")

    assert metric.metric_name == "row_count"
    assert metric.value == 1000.0
    assert metric.computed_at == computed_at
    assert metric.details is None
