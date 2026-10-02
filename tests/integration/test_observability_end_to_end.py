"""End-to-end: validate -> persist -> read back through ObservabilityQueryService.

Same setup as test_end_to_end.py (every rule fails), plus the Postgres test
store.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sentinel.domain import Criticality, Dataset, Status
from sentinel.observability.queries import ObservabilityQueryService, TimeWindow
from sentinel.observability.views import RecurrenceClassification
from sentinel.orchestration import ValidationOrchestrator
from sentinel.persistence.engine import StoreConnection
from sentinel.persistence.writer import persist_validation_run
from sentinel.policy_loader import load_policy
from sentinel.registration import register_all
from tests.unit.doubles import FakeDataSource

FIXTURES_ROOT = Path(__file__).parents[1] / "fixtures"


def _orders_data_source() -> FakeDataSource:
    path = FIXTURES_ROOT / "data" / "orders.csv"
    with path.open(newline="") as f:
        rows = [
            {key: (value if value != "" else None) for key, value in row.items()}
            for row in csv.DictReader(f)
        ]
    return FakeDataSource(rows=rows)


def _orders_dataset() -> Dataset:
    return Dataset(
        id="orders",
        name="orders",
        source_type="csv",
        environment="test",
        owner="data-platform-team",
        criticality=Criticality.HIGH,
    )


def test_validate_then_persist_then_observe(store: StoreConnection) -> None:
    register_all()
    policy = load_policy(FIXTURES_ROOT / "policies" / "orders_m1.yaml")
    source = _orders_data_source()
    dataset = _orders_dataset()

    run = ValidationOrchestrator().run(dataset=dataset, policy=policy, source=source)
    assert run.status is Status.FAIL  # every rule fails against this fixture (see module docstring)
    assert len(run.incidents) == 3  # one per non-PASS event -- all three rules failed

    run_id = persist_validation_run(store, run)

    service = ObservabilityQueryService(store)
    as_of = run.finished_at

    # Dataset Health: only failures, so neither HEALTHY nor UNKNOWN.
    health = service.dataset_health("orders")
    assert health.dataset_id == "orders"
    assert health.health.value in {"degraded", "critical"}
    assert health.failed_rules == 3
    assert health.highest_incident_priority in {"info", "warning", "high", "critical"}
    assert health.latest_run_status == "fail"

    # Quality History: exactly the one run, all three rules failed.
    history = service.quality_history("orders", TimeWindow.LAST_30D, as_of)
    assert len(history) == 1
    assert history[0].run_id == run_id
    assert history[0].rules_evaluated == 3
    assert history[0].rules_failed == 3
    assert history[0].overall_status == "fail"

    # Metric Trends: one point per rule; threshold details survive the round trip.
    row_count_trend = service.metric_trend("orders", "row_count", TimeWindow.LAST_30D, as_of)
    assert len(row_count_trend) == 1
    assert row_count_trend[0].value == 12.0
    assert row_count_trend[0].threshold_details is not None
    assert json.loads(row_count_trend[0].threshold_details)["actual"] == 12.0

    null_rate_trend = service.metric_trend(
        "orders", "customer_id_not_null", TimeWindow.LAST_30D, as_of
    )
    assert len(null_rate_trend) == 1
    assert null_rate_trend[0].value == 1 / 12

    # Failed Rules: each rule failed once and has a priority.
    failed = {view.rule_name: view for view in service.failed_rules(TimeWindow.LAST_30D, as_of)}
    assert set(failed) == {"row_count", "customer_id_not_null", "unique_order_id"}
    for view in failed.values():
        assert view.failure_count == 1
        assert view.current_priority in {"info", "warning", "high", "critical"}

    # Incident History: one entry per failed rule, each explainable.
    incidents = service.incident_history(TimeWindow.LAST_30D, as_of, dataset_id="orders")
    assert len(incidents) == 3
    assert all(entry.top_reason is not None for entry in incidents)

    # Recurring Failures: only one run, so all are first occurrences.
    recurring = service.recurring_failures(TimeWindow.LAST_30D, as_of)
    assert len(recurring) == 3
    assert all(
        view.classification is RecurrenceClassification.FIRST_OCCURRENCE for view in recurring
    )
