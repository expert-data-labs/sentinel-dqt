from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import ClassVar

import pytest

from sentinel.domain import Metric, Status, ThresholdConfig, ThresholdResult
from sentinel.thresholds import (
    ThresholdStrategyNotRegisteredError,
    get_threshold_strategy,
    register_threshold_strategy,
)
from sentinel.thresholds import registry as registry_module
from tests.unit.doubles import DummyThresholdStrategy


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Save, clear and restore the registry around each test."""
    original = dict(registry_module._REGISTRY)
    registry_module._REGISTRY.clear()
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(original)


def _metric(value: float = 500.0) -> Metric:
    return Metric(metric_name="row_count", value=value, computed_at=datetime.now(UTC))


def _threshold_config() -> ThresholdConfig:
    return ThresholdConfig(strategy="always_pass", params={"min": 1000})


def test_register_and_resolve_a_dummy_strategy() -> None:
    @register_threshold_strategy
    class AlwaysPassStrategy:
        strategy_type: ClassVar[str] = "always_pass"

        def evaluate(
            self, metric: Metric, config: ThresholdConfig, history: Sequence[Metric] = ()
        ) -> ThresholdResult:
            return ThresholdResult(
                status=Status.PASS, expected="always passes", strategy_type=self.strategy_type
            )

    strategy = get_threshold_strategy("always_pass")
    assert isinstance(strategy, AlwaysPassStrategy)

    result = strategy.evaluate(metric=_metric(), config=_threshold_config())
    assert result.status is Status.PASS
    assert result.strategy_type == "always_pass"


def test_unregistered_strategy_type_raises_with_known_types_listed() -> None:
    @register_threshold_strategy
    class AlwaysPassStrategy:
        strategy_type: ClassVar[str] = "always_pass"

        def evaluate(
            self, metric: Metric, config: ThresholdConfig, history: Sequence[Metric] = ()
        ) -> ThresholdResult:
            return ThresholdResult(
                status=Status.PASS, expected="always passes", strategy_type=self.strategy_type
            )

    with pytest.raises(ThresholdStrategyNotRegisteredError, match="always_pass"):
        get_threshold_strategy("does_not_exist")


def test_registering_a_duplicate_strategy_type_raises() -> None:
    @register_threshold_strategy
    class FirstStrategy:
        strategy_type: ClassVar[str] = "duplicate"

        def evaluate(
            self, metric: Metric, config: ThresholdConfig, history: Sequence[Metric] = ()
        ) -> ThresholdResult:
            return ThresholdResult(
                status=Status.PASS, expected="n/a", strategy_type=self.strategy_type
            )

    with pytest.raises(ValueError, match="duplicate"):

        @register_threshold_strategy
        class SecondStrategy:
            strategy_type: ClassVar[str] = "duplicate"

            def evaluate(
                self, metric: Metric, config: ThresholdConfig, history: Sequence[Metric] = ()
            ) -> ThresholdResult:
                return ThresholdResult(
                    status=Status.FAIL, expected="n/a", strategy_type=self.strategy_type
                )


def test_dummy_threshold_strategy_satisfies_the_protocol_and_ignores_its_inputs() -> None:
    strategy = DummyThresholdStrategy(status=Status.WARN)
    result = strategy.evaluate(metric=_metric(), config=_threshold_config())
    assert result.status is Status.WARN
    assert result.strategy_type == "dummy"
