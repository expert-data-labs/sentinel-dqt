from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import ClassVar

import pytest

from sentinel.datasources import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules import RuleNotRegisteredError, get_rule, register_rule
from sentinel.rules import registry as registry_module
from tests.unit.doubles import DummyRule, FakeDataSource


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Save, clear and restore the registry around each test."""
    original = dict(registry_module._REGISTRY)
    registry_module._REGISTRY.clear()
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(original)


def _rule_config(rule_type: str) -> RuleConfig:
    return RuleConfig.model_validate(
        {
            "name": "some_rule",
            "type": rule_type,
            "threshold": {"strategy": "static", "min": 1},
        }
    )


def test_register_and_resolve_a_dummy_rule() -> None:
    @register_rule
    class EchoRule:
        rule_type: ClassVar[str] = "echo"

        def compute(self, source: DataSource, config: RuleConfig) -> Metric:
            return Metric(metric_name=config.name, value=42.0, computed_at=datetime.now(UTC))

    rule = get_rule("echo")
    assert isinstance(rule, EchoRule)

    metric = rule.compute(source=object(), config=_rule_config("echo"))  # type: ignore[arg-type]
    assert metric.value == 42.0


def test_unregistered_rule_type_raises_with_known_types_listed() -> None:
    @register_rule
    class EchoRule:
        rule_type: ClassVar[str] = "echo"

        def compute(self, source: DataSource, config: RuleConfig) -> Metric:
            return Metric(metric_name=config.name, value=0.0, computed_at=datetime.now(UTC))

    with pytest.raises(RuleNotRegisteredError, match="echo"):
        get_rule("does_not_exist")


def test_dummy_rule_satisfies_the_rule_protocol_and_ignores_its_inputs() -> None:
    rule = DummyRule(value=7.0)
    metric = rule.compute(source=FakeDataSource(rows=[]), config=_rule_config("dummy"))
    assert metric.metric_name == "some_rule"
    assert metric.value == 7.0


def test_registering_a_duplicate_rule_type_raises() -> None:
    @register_rule
    class FirstRule:
        rule_type: ClassVar[str] = "duplicate"

        def compute(self, source: DataSource, config: RuleConfig) -> Metric:
            return Metric(metric_name=config.name, value=0.0, computed_at=datetime.now(UTC))

    with pytest.raises(ValueError, match="duplicate"):

        @register_rule
        class SecondRule:
            rule_type: ClassVar[str] = "duplicate"

            def compute(self, source: DataSource, config: RuleConfig) -> Metric:
                return Metric(metric_name=config.name, value=1.0, computed_at=datetime.now(UTC))
