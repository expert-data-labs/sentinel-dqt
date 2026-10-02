from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import ClassVar

import pytest

from sentinel.domain import (
    Criticality,
    Dataset,
    Metric,
    Policy,
    Status,
    ThresholdConfig,
    ThresholdResult,
)
from sentinel.orchestration import ValidationOrchestrator
from sentinel.orchestration.orchestrator import _worst_status
from sentinel.rules import register_rule
from sentinel.rules import registry as rule_registry_module
from sentinel.thresholds import register_threshold_strategy
from sentinel.thresholds import registry as threshold_registry_module
from tests.unit.doubles import (
    DummyRule,
    DummyThresholdStrategy,
    FakeDataSource,
    FakeFailureHistorySource,
    FakeHistorySource,
)


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


class _HistoryCapturingStrategy:
    """A ThresholdStrategy whose only job is to record the ``history`` it
    was called with, so a test can assert on exactly what the orchestrator
    fetched and passed through — the orchestrator's one Milestone 4
    responsibility (see orchestrator.py's own docstring).

    ``received`` is a ClassVar, not instance state: the orchestrator asks
    the registry for a fresh instance per rule (registry.get_threshold_strategy
    calls ``strategy_cls()`` each time), so a test that wants to see calls
    across every rule in a run needs somewhere shared to record them. Tests
    using this double reset it themselves before running the orchestrator.
    """

    strategy_type: ClassVar[str] = "history_capturing"
    received: ClassVar[list[Sequence[Metric]]] = []

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        type(self).received.append(history)
        return ThresholdResult(status=Status.PASS, expected="n/a", strategy_type=self.strategy_type)


def _dataset(dataset_id: str = "orders") -> Dataset:
    return Dataset(
        id=dataset_id,
        name=dataset_id,
        source_type="duckdb",
        environment="production",
        owner="data-platform-team",
        criticality=Criticality.HIGH,
    )


def _policy(*rule_names: str, strategy: str = "dummy") -> Policy:
    return Policy.model_validate(
        {
            "dataset": "orders",
            "rules": [
                {
                    "name": name,
                    "type": "dummy",
                    "threshold": {"strategy": strategy, "min": 1},
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


def test_default_history_source_supplies_empty_history() -> None:
    """No history_source passed in -> NullHistorySource -> every strategy
    call sees (), same as every Milestone 0-3 construction site does today
    (ValidationOrchestrator() with no arguments)."""
    register_rule(DummyRule)
    register_threshold_strategy(_HistoryCapturingStrategy)
    _HistoryCapturingStrategy.received = []

    ValidationOrchestrator().run(
        dataset=_dataset(),
        policy=_policy("row_count", strategy="history_capturing"),
        source=FakeDataSource(rows=[]),
    )

    assert _HistoryCapturingStrategy.received == [()]


def test_history_source_result_is_scoped_by_dataset_id_and_rule_name_and_passed_through() -> None:
    register_rule(DummyRule)
    register_threshold_strategy(_HistoryCapturingStrategy)
    _HistoryCapturingStrategy.received = []

    row_count_history = (
        Metric(metric_name="row_count", value=1000.0, computed_at=datetime.now(UTC)),
    )
    history_source = FakeHistorySource(
        history={
            ("orders", "row_count"): row_count_history,
            ("orders", "null_rate"): (),
            ("some_other_dataset", "row_count"): (
                Metric(metric_name="row_count", value=999.0, computed_at=datetime.now(UTC)),
            ),
        }
    )

    ValidationOrchestrator(history_source=history_source).run(
        dataset=_dataset("orders"),
        policy=_policy("row_count", "null_rate", strategy="history_capturing"),
        source=FakeDataSource(rows=[]),
    )

    assert _HistoryCapturingStrategy.received == [row_count_history, ()]


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


# -- Milestone 5: incident prioritization integration -------------------------
#
# DummyThresholdStrategy always answers Status.PASS regardless of any
# constructor argument -- the registry builds a fresh instance with no
# args each time (see registry.get_threshold_strategy) -- so the tests
# below that need a FAIL/WARN verdict register their own small strategy
# double instead, the same pattern _HistoryCapturingStrategy above
# already establishes for Milestone 4.


def test_default_prioritizer_produces_an_incident_for_a_failing_event() -> None:
    class _FailingStrategy:
        strategy_type: ClassVar[str] = "always_fail"

        def evaluate(
            self,
            metric: Metric,
            config: ThresholdConfig,
            history: Sequence[Metric] = (),
        ) -> ThresholdResult:
            return ThresholdResult(
                status=Status.FAIL, expected="n/a", strategy_type=self.strategy_type
            )

    register_rule(DummyRule)
    register_threshold_strategy(_FailingStrategy)

    run = ValidationOrchestrator().run(
        dataset=_dataset(),
        policy=_policy("row_count", strategy="always_fail"),
        source=FakeDataSource(rows=[]),
    )

    assert run.status is Status.FAIL
    assert len(run.incidents) == 1
    assert run.incidents[0].quality_event is run.quality_events[0]


def test_passing_events_produce_no_incidents() -> None:
    register_rule(DummyRule)
    register_threshold_strategy(DummyThresholdStrategy)  # defaults to Status.PASS

    run = ValidationOrchestrator().run(
        dataset=_dataset(), policy=_policy("row_count"), source=FakeDataSource(rows=[])
    )

    assert run.status is Status.PASS
    assert run.incidents == ()


def test_incidents_are_only_produced_for_non_pass_events_among_several_rules() -> None:
    """Edge case: multiple QualityEvents in one ValidationRun -- some pass,
    some don't; only the non-PASS ones get an Incident, and run.incidents
    stays shorter than run.quality_events."""

    class _MixedStrategy:
        strategy_type: ClassVar[str] = "mixed"

        def evaluate(
            self,
            metric: Metric,
            config: ThresholdConfig,
            history: Sequence[Metric] = (),
        ) -> ThresholdResult:
            status = Status.FAIL if metric.metric_name == "null_rate" else Status.PASS
            return ThresholdResult(status=status, expected="n/a", strategy_type=self.strategy_type)

    register_rule(DummyRule)
    register_threshold_strategy(_MixedStrategy)

    run = ValidationOrchestrator().run(
        dataset=_dataset(),
        policy=_policy("row_count", "null_rate", strategy="mixed"),
        source=FakeDataSource(rows=[]),
    )

    assert len(run.quality_events) == 2
    assert len(run.incidents) == 1
    assert run.incidents[0].quality_event.rule_name == "null_rate"


def test_default_failure_history_source_treats_every_failure_as_first_occurrence() -> None:
    """No failure_history_source passed in -> NullFailureHistorySource ->
    every non-PASS event is scored as a first occurrence, same discipline
    Milestone 4's NullHistorySource default already established."""

    class _FailingStrategy:
        strategy_type: ClassVar[str] = "always_fail_2"

        def evaluate(
            self,
            metric: Metric,
            config: ThresholdConfig,
            history: Sequence[Metric] = (),
        ) -> ThresholdResult:
            return ThresholdResult(
                status=Status.FAIL, expected="n/a", strategy_type=self.strategy_type
            )

    register_rule(DummyRule)
    register_threshold_strategy(_FailingStrategy)

    run = ValidationOrchestrator().run(
        dataset=_dataset(),
        policy=_policy("row_count", strategy="always_fail_2"),
        source=FakeDataSource(rows=[]),
    )

    assert run.incidents[0].components.frequency_score == 10.0


def test_failure_history_source_is_scoped_by_dataset_id_and_rule_name() -> None:
    class _FailingStrategy:
        strategy_type: ClassVar[str] = "always_fail_3"

        def evaluate(
            self,
            metric: Metric,
            config: ThresholdConfig,
            history: Sequence[Metric] = (),
        ) -> ThresholdResult:
            return ThresholdResult(
                status=Status.FAIL, expected="n/a", strategy_type=self.strategy_type
            )

    register_rule(DummyRule)
    register_threshold_strategy(_FailingStrategy)

    failure_history_source = FakeFailureHistorySource(
        outcomes={("orders", "row_count"): (Status.FAIL,) * 9 + (Status.PASS,)}
    )

    run = ValidationOrchestrator(failure_history_source=failure_history_source).run(
        dataset=_dataset("orders"),
        policy=_policy("row_count", strategy="always_fail_3"),
        source=FakeDataSource(rows=[]),
    )

    incident = run.incidents[0]
    assert incident.components.frequency_score > 10.0  # not treated as a first occurrence

