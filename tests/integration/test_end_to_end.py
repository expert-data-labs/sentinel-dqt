"""Milestone 1's acceptance test: the milestone's own diagram

    Policy -> Rule Resolution -> Rule Execution -> Metric ->
    Threshold Evaluation -> Quality Event -> Validation Run Result

made executable, with no dummies anywhere. Unlike tests/unit/, which
exercises one component at a time (often against DummyRule/
DummyThresholdStrategy), this loads the real orders_m1.yaml policy through
the real load_policy(), registers the real Milestone 1 rules and the real
static threshold strategy via register_all(), and runs them through the
real ValidationOrchestrator against a FakeDataSource seeded from the
existing orders.csv fixture.

orders_m1.yaml (not orders.yaml) is used deliberately: orders.yaml also
declares a `freshness` rule, which has no Rule implementation until
Milestone 3 — running it through a real orchestrator today would raise
RuleNotRegisteredError. See orders_m1.yaml's own header comment.

orders.csv's 12 rows were built (Milestone 0) to exercise exactly the
edge cases this test needs: one null customer_id and one duplicate
order_id. Against the PRD's own thresholds (min: 1000 rows, max: 1% nulls,
max: 0 duplicates) every rule here is expected to fail — this is a small
sample fixture, not a production-sized table. That's a feature for this
test: it proves the pipeline computes *and correctly judges* real
measurements, not just that it runs without crashing.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sentinel.domain import Criticality, Dataset, Status
from sentinel.orchestration import ValidationOrchestrator
from sentinel.policy_loader import load_policy
from sentinel.registration import register_all
from tests.unit.doubles import FakeDataSource

FIXTURES_ROOT = Path(__file__).parents[1] / "fixtures"


def _orders_data_source() -> FakeDataSource:
    """Load orders.csv into a FakeDataSource, treating empty CSV fields as
    null (csv.DictReader gives back "" for an empty field, not None, and
    DataSource's null semantics are defined in terms of None)."""
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


def test_orders_m1_policy_runs_end_to_end_against_the_sample_fixture() -> None:
    register_all()
    policy = load_policy(FIXTURES_ROOT / "policies" / "orders_m1.yaml")
    source = _orders_data_source()

    run = ValidationOrchestrator().run(dataset=_orders_dataset(), policy=policy, source=source)

    events_by_name = {event.rule_name: event for event in run.quality_events}
    assert set(events_by_name) == {"row_count", "customer_id_not_null", "unique_order_id"}

    row_count_event = events_by_name["row_count"]
    assert row_count_event.actual == 12.0
    assert row_count_event.status is Status.FAIL  # 12 rows, threshold requires >= 1000
    assert row_count_event.expected == "row_count >= 1000"

    null_rate_event = events_by_name["customer_id_not_null"]
    assert null_rate_event.actual == 1 / 12  # one null customer_id (order 1004) of 12 rows
    assert null_rate_event.status is Status.FAIL  # ~8.3% nulls, threshold requires <= 1%

    uniqueness_event = events_by_name["unique_order_id"]
    assert uniqueness_event.actual == 1.0  # order_id 1007 appears twice
    assert uniqueness_event.status is Status.FAIL  # 1 duplicate, threshold requires 0
    assert uniqueness_event.expected == "unique_order_id <= 0"

    # Worst-status-wins aggregation (Milestone 0's orchestrator): every
    # event failed, so the run as a whole is a FAIL.
    assert run.status is Status.FAIL
    assert run.dataset.name == "orders"
    assert run.policy_version == policy.version
