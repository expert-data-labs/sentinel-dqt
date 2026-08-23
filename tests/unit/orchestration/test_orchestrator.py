from __future__ import annotations

from collections.abc import Iterator

import pytest

from sentinel.domain import Criticality, Dataset, Policy, Status
from sentinel.orchestration import ValidationOrchestrator
from sentinel.orchestration.orchestrator import _worst_status
from sentinel.rules import register_rule
from sentinel.rules import registry as rule_registry_module
from sentinel.thresholds import register_threshold_strategy
from sentinel.thresholds import registry as threshold_registry_module
from tests.unit.doubles import DummyRule, DummyThresholdStrategy, FakeDataSource


@pytest.fixture(autouse=True)
def _isolated_registries() -> Iterator[None]:
    """Registering dummies for these tests shouldn't leak into other test
    modules, or into whatever real rules/strategies Milestone 1 eventually
    registers at import time."""
    original_rules = dict(rule_registry_module._REGISTRY)
    original_strategies = dict(threshold_registry_module._REGISTRY)
    rule_registry_module._REGISTRY.clear()
    threshold_registry_module._REGISTRY.clear()
    yield
    rule_registry_module._REGISTRY.clear()
    rule_registry_module._REGISTRY.update(original_rules)
    threshold_registry_module._REGISTRY.clear()
    threshold_registry_module._REGISTRY.update(original_strategies)


def _dataset() -> Dataset:
    return Dataset(
        id="orders",
        name="orders",
        source_type="duckdb",
        environment="production",
        owner="data-platform-team",
        criticality=Criticality.HIGH,
    )


def _policy(*rule_names: str) -> Policy:
    return Policy.model_validate(
        {
            "dataset": "orders",
            "rules": [
                {
                    "name": name,
                    "type": "dummy",
                    "threshold": {"strategy": "dummy", "min": 1},
                }
                for name in rule_names
            ],
        }
    )


def test_run_wires_rule_and_threshold_into_a_single_quality_event() -> None:
    register_rule(DummyRule)
    register_threshold_strategy(DummyThresholdStrategy)

    run = ValidationOrchestrator().run(
        dataset=_dataset(), policy=_policy("row_count"), source=FakeDataSource(rows=[])
    )

    assert run.dataset.id == "orders"
    assert run.policy_version == "unversioned"
    assert run.finished_at >= run.started_at
    assert len(run.quality_events) == 1

    event = run.quality_events[0]
    assert event.rule_name == "row_count"
    assert event.status is Status.PASS
    assert event.blocking is True
    assert run.status is Status.PASS


def test_run_collects_one_event_per_rule_in_the_policy() -> None:
    register_rule(DummyRule)
    register_threshold_strategy(DummyThresholdStrategy)

    run = ValidationOrchestrator().run(
        dataset=_dataset(),
        policy=_policy("row_count", "null_rate"),
        source=FakeDataSource(rows=[]),
    )

    assert [event.rule_name for event in run.quality_events] == ["row_count", "null_rate"]
    assert run.status is Status.PASS


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], Status.PASS),
        ([Status.PASS], Status.PASS),
        ([Status.PASS, Status.WARN], Status.WARN),
        ([Status.WARN, Status.FAIL], Status.FAIL),
        ([Status.FAIL, Status.PASS, Status.WARN], Status.FAIL),
    ],
)
def test_worst_status_picks_the_most_severe(statuses: list[Status], expected: Status) -> None:
    assert _worst_status(statuses) is expected
