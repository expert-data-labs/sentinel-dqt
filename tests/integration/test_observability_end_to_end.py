"""Milestone 6's own required end-to-end flow:

    Run validation -> Persist results -> Open observability query
        -> Dashboard receives expected data

Extends tests/integration/test_end_to_end.py's own pattern exactly: the
real orders_m1.yaml policy, the real Milestone 1 rules and static
threshold strategy via register_all(), a real ValidationOrchestrator
against a FakeDataSource seeded from orders.csv -- no dummies anywhere in
the domain/application layers. What's new here is the second half:
persisting that real ValidationRun to a real (temp-file) DuckDB store
and reading it back through ObservabilityQueryService, proving the
whole pipeline this milestone's own diagram describes (Validation ->
Metric -> QualityEvent -> Incident Priority -> Persistence ->
Observability Queries -> Dashboard) actually holds together end to end.

Every rule in orders_m1.yaml fails against the 12-row orders.csv fixture
(see test_end_to_end.py's own docstring for why that's a deliberate,
useful property of this fixture, not a bug) -- so every quality event
here reaches IncidentPrioritizer for real (ValidationOrchestrator's
default failure_history_source/prioritizer, exercised with zero
injected history, exactly like every Milestone 0-4 call site that never
opted into Milestone 5's new arguments).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sentinel.domain import Criticality, Dataset, Status
from sentinel.observability.queries import ObservabilityQueryService, TimeWindow
from sentinel.observability.views import RecurrenceClassification
from sentinel.orchestration import ValidationOrchestrator
from sentinel.persistence.engine import get_connection
from sentinel.persistence.schema import ensure_schema
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


def test_validate_then_persist_then_observe(tmp_path: Path) -> None:
    register_all()
    policy = load_policy(FIXTURES_ROOT / "policies" / "orders_m1.yaml")
    source = _orders_data_source()
    dataset = _orders_dataset()

    run = ValidationOrchestrator().run(dataset=dataset, policy=policy, source=source)
    assert run.status is Status.FAIL  # every rule fails against this fixture (see module docstring)
    assert len(run.incidents) == 3  # one per non-PASS event -- all three rules failed

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_schema(conn)
    run_id = persist_validation_run(conn, run)

    service = ObservabilityQueryService(conn)
    as_of = run.finished_at

    # Dataset Health: a dataset with only failures is never HEALTHY or
    # UNKNOWN (a run did happen), and it has a real incident priority.
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

    # Metric Trends: one point per rule, and the static strategy's
    # Milestone-5 `details` addition survives the round trip through
    # persistence -- never recomputed here, read back verbatim.
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

    # Failed Rules: all three rules, each having failed exactly once, each
    # carrying whatever priority IncidentPrioritizer computed for it.
    failed = {view.rule_name: view for view in service.failed_rules(TimeWindow.LAST_30D, as_of)}
    assert set(failed) == {"row_count", "customer_id_not_null", "unique_order_id"}
    for view in failed.values():
        assert view.failure_count == 1
        assert view.current_priority in {"info", "warning", "high", "critical"}

    # Incident History: one entry per failed rule, each explainable.
    incidents = service.incident_history(TimeWindow.LAST_30D, as_of, dataset_id="orders")
    assert len(incidents) == 3
    assert all(entry.top_reason is not None for entry in incidents)

    # Recurring Failures: exactly one validation run has ever happened,
    # so every pair is a first occurrence, never RECURRING or PERSISTENT.
    recurring = service.recurring_failures(TimeWindow.LAST_30D, as_of)
    assert len(recurring) == 3
    assert all(
        view.classification is RecurrenceClassification.FIRST_OCCURRENCE for view in recurring
    )
