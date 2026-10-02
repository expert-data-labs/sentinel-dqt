"""ObservabilityQueryService against a real temp DuckDB store (see fixtures.py).

Times relative to fixtures.AS_OF (2026-09-06 12:00 UTC):

    payments/null_rate FAILs at t-10d, t-5d, t-2d, t-3h (4 total)
    payments/row_count FAILs once, at t-2d
    customers/duplicate_count WARNs once, at t-1d
    orders always PASSes
    unvalidated_dataset has never been validated
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import duckdb

from sentinel.domain import IncidentPriority
from sentinel.observability.queries import ObservabilityQueryService, TimeWindow
from sentinel.observability.views import DatasetHealth, RecurrenceClassification
from sentinel.persistence.engine import get_connection
from sentinel.persistence.schema import ensure_schema
from tests.unit.observability.fixtures import (
    AS_OF,
    CUSTOMERS_ID,
    ORDERS_ID,
    PAYMENTS_ID,
    UNVALIDATED_DATASET_ID,
    seed_default_fixture,
)


def _service(tmp_path: Path) -> ObservabilityQueryService:
    conn: duckdb.DuckDBPyConnection = get_connection(tmp_path / "test.duckdb")
    ensure_schema(conn)
    seed_default_fixture(conn)
    return ObservabilityQueryService(conn)


# -- Dataset Health --


def test_all_datasets_health_covers_every_registered_dataset(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = service.all_datasets_health()
    assert {v.dataset_id for v in views} == {
        ORDERS_ID,
        PAYMENTS_ID,
        CUSTOMERS_ID,
        UNVALIDATED_DATASET_ID,
    }


def test_orders_is_healthy(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = {v.dataset_id: v for v in service.all_datasets_health()}
    orders = views[ORDERS_ID]
    assert orders.health is DatasetHealth.HEALTHY
    assert orders.failed_rules == 0
    assert orders.highest_incident_priority is None
    assert orders.latest_run_status == "pass"
    assert orders.latest_validation_at == AS_OF - timedelta(hours=1)


def test_payments_is_critical_on_its_latest_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = {v.dataset_id: v for v in service.all_datasets_health()}
    payments = views[PAYMENTS_ID]
    assert payments.health is DatasetHealth.CRITICAL
    assert payments.highest_incident_priority == "critical"
    assert payments.failed_rules == 1  # null_rate failed on run D, row_count passed
    assert payments.latest_validation_at == AS_OF - timedelta(hours=3)


def test_customers_is_degraded_by_a_warning_incident(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = {v.dataset_id: v for v in service.all_datasets_health()}
    customers = views[CUSTOMERS_ID]
    assert customers.health is DatasetHealth.DEGRADED
    assert customers.highest_incident_priority == "warning"


def test_never_validated_dataset_is_unknown(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = {v.dataset_id: v for v in service.all_datasets_health()}
    unvalidated = views[UNVALIDATED_DATASET_ID]
    assert unvalidated.health is DatasetHealth.UNKNOWN
    assert unvalidated.latest_validation_at is None
    assert unvalidated.highest_incident_priority is None


def test_dataset_health_single_lookup_matches_the_bulk_view(tmp_path: Path) -> None:
    service = _service(tmp_path)
    bulk = {v.dataset_id: v for v in service.all_datasets_health()}
    single = service.dataset_health(PAYMENTS_ID)
    assert single == bulk[PAYMENTS_ID]


def test_dataset_health_raises_for_an_unregistered_dataset(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        service.dataset_health("does_not_exist")
    except ValueError:
        return
    raise AssertionError("expected ValueError for an unregistered dataset id")


# -- Quality History --


def test_quality_history_respects_the_time_window(tmp_path: Path) -> None:
    service = _service(tmp_path)
    last_30d = service.quality_history(PAYMENTS_ID, TimeWindow.LAST_30D, AS_OF)
    last_7d = service.quality_history(PAYMENTS_ID, TimeWindow.LAST_7D, AS_OF)
    last_24h = service.quality_history(PAYMENTS_ID, TimeWindow.LAST_24H, AS_OF)
    assert len(last_30d) == 4  # runs A, B, C, D
    assert len(last_7d) == 3  # B, C, D -- A (t-10d) falls outside 7 days
    assert len(last_24h) == 1  # only D (t-3h)


def test_quality_history_is_ordered_most_recent_first(tmp_path: Path) -> None:
    service = _service(tmp_path)
    entries = service.quality_history(PAYMENTS_ID, TimeWindow.LAST_30D, AS_OF)
    started_ats = [entry.started_at for entry in entries]
    assert started_ats == sorted(started_ats, reverse=True)


def test_quality_history_counts_and_priorities_per_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    entries = {
        entry.started_at: entry
        for entry in service.quality_history(PAYMENTS_ID, TimeWindow.LAST_30D, AS_OF)
    }
    run_c = entries[AS_OF - timedelta(days=2)]
    assert run_c.rules_evaluated == 2
    assert run_c.rules_failed == 2  # both null_rate and row_count failed
    assert run_c.overall_status == "fail"
    assert run_c.highest_incident_priority == "critical"  # null_rate's incident, not row_count's

    run_a = entries[AS_OF - timedelta(days=10)]
    assert run_a.rules_failed == 1
    assert run_a.highest_incident_priority == "high"


# -- Metric Trends --


def test_metric_trend_returns_points_in_chronological_order(tmp_path: Path) -> None:
    service = _service(tmp_path)
    points = service.metric_trend(PAYMENTS_ID, "null_rate", TimeWindow.LAST_30D, AS_OF)
    assert [p.value for p in points] == [0.18, 0.21, 0.24, 0.30]
    computed_ats = [p.computed_at for p in points]
    assert computed_ats == sorted(computed_ats)


def test_metric_trend_carries_the_threshold_details_json(tmp_path: Path) -> None:
    service = _service(tmp_path)
    points = service.metric_trend(PAYMENTS_ID, "null_rate", TimeWindow.LAST_30D, AS_OF)
    assert all(p.threshold_details is not None for p in points)
    assert '"actual": 0.18' in points[0].threshold_details  # type: ignore[operator]


def test_metric_trend_respects_the_time_window(tmp_path: Path) -> None:
    service = _service(tmp_path)
    points = service.metric_trend(PAYMENTS_ID, "null_rate", TimeWindow.LAST_7D, AS_OF)
    assert len(points) == 3  # B, C, D -- A falls outside 7 days


# -- Failed Rules --


def test_failed_rules_across_all_datasets(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = service.failed_rules(TimeWindow.LAST_30D, AS_OF)
    by_key = {(v.dataset_id, v.rule_name): v for v in views}

    assert by_key[(PAYMENTS_ID, "null_rate")].failure_count == 4
    assert by_key[(PAYMENTS_ID, "null_rate")].current_priority == "critical"
    assert by_key[(PAYMENTS_ID, "row_count")].failure_count == 1
    assert by_key[(PAYMENTS_ID, "row_count")].current_priority == "warning"
    assert by_key[(CUSTOMERS_ID, "duplicate_count")].failure_count == 1
    assert (ORDERS_ID, "row_count") not in by_key  # orders never fails


def test_failed_rules_is_ordered_by_failure_count_descending(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = service.failed_rules(TimeWindow.LAST_30D, AS_OF)
    counts = [v.failure_count for v in views]
    assert counts == sorted(counts, reverse=True)
    assert views[0].rule_name == "null_rate"  # the uniquely highest count, 4


def test_failed_rules_can_be_filtered_by_dataset(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = service.failed_rules(TimeWindow.LAST_30D, AS_OF, dataset_id=CUSTOMERS_ID)
    assert {v.dataset_id for v in views} == {CUSTOMERS_ID}


# -- Incident History --


def test_incident_history_count_and_order(tmp_path: Path) -> None:
    service = _service(tmp_path)
    entries = service.incident_history(TimeWindow.LAST_30D, AS_OF)
    assert len(entries) == 6  # A, B, C(x2), D for payments + 1 for customers
    occurred_ats = [entry.occurred_at for entry in entries]
    assert occurred_ats == sorted(occurred_ats, reverse=True)


def test_incident_history_respects_the_time_window(tmp_path: Path) -> None:
    service = _service(tmp_path)
    entries = service.incident_history(TimeWindow.LAST_7D, AS_OF)
    assert len(entries) == 5  # everything except run A (t-10d)


def test_incident_history_can_be_filtered_by_priority(tmp_path: Path) -> None:
    service = _service(tmp_path)
    entries = service.incident_history(
        TimeWindow.LAST_30D, AS_OF, priority=IncidentPriority.CRITICAL
    )
    assert len(entries) == 2  # run C's null_rate incident, and run D's
    assert all(e.priority == "critical" for e in entries)
    assert all(e.rule_name == "null_rate" for e in entries)


def test_incident_history_can_be_filtered_by_dataset_and_rule(tmp_path: Path) -> None:
    service = _service(tmp_path)
    entries = service.incident_history(
        TimeWindow.LAST_30D, AS_OF, dataset_id=PAYMENTS_ID, rule_name="row_count"
    )
    assert len(entries) == 1
    assert entries[0].priority == "warning"


def test_incident_history_top_reason_is_the_first_reason(tmp_path: Path) -> None:
    service = _service(tmp_path)
    entries = service.incident_history(
        TimeWindow.LAST_30D, AS_OF, dataset_id=CUSTOMERS_ID
    )
    assert entries[0].top_reason == "Dataset criticality: MEDIUM"


# -- Recurring Failures --


def test_recurring_failures_classification_over_30_days(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = {(v.dataset_id, v.rule_name): v for v in service.recurring_failures(
        TimeWindow.LAST_30D, AS_OF
    )}
    # null_rate: 4 failures in-window, most recent evaluation (run D) also failed.
    assert views[(PAYMENTS_ID, "null_rate")].failure_count == 4
    assert views[(PAYMENTS_ID, "null_rate")].classification is (
        RecurrenceClassification.PERSISTENT
    )
    # row_count: exactly 1 failure ever.
    assert views[(PAYMENTS_ID, "row_count")].failure_count == 1
    assert views[(PAYMENTS_ID, "row_count")].classification is (
        RecurrenceClassification.FIRST_OCCURRENCE
    )
    assert views[(CUSTOMERS_ID, "duplicate_count")].classification is (
        RecurrenceClassification.FIRST_OCCURRENCE
    )


def test_recurring_failures_within_24h_window_reflects_only_that_window(
    tmp_path: Path,
) -> None:
    """null_rate failed only once in the last 24h, so it's a first occurrence in
    that window.
    """
    service = _service(tmp_path)
    views = {(v.dataset_id, v.rule_name): v for v in service.recurring_failures(
        TimeWindow.LAST_24H, AS_OF
    )}
    assert views[(PAYMENTS_ID, "null_rate")].failure_count == 1
    assert views[(PAYMENTS_ID, "null_rate")].classification is (
        RecurrenceClassification.FIRST_OCCURRENCE
    )
    # row_count's only failure (run C, t-2d) is outside the 24h window entirely.
    assert (PAYMENTS_ID, "row_count") not in views


def test_recurring_failures_can_be_filtered_by_dataset(tmp_path: Path) -> None:
    service = _service(tmp_path)
    views = service.recurring_failures(TimeWindow.LAST_30D, AS_OF, dataset_id=ORDERS_ID)
    assert views == []  # orders never fails


# -- rule_names_for_dataset (dashboard selector glue) --


def test_rule_names_for_dataset_returns_every_rule_ever_evaluated(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.rule_names_for_dataset(PAYMENTS_ID) == ["null_rate", "row_count"]


def test_rule_names_for_dataset_is_empty_for_a_never_validated_dataset(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.rule_names_for_dataset(UNVALIDATED_DATASET_ID) == []
