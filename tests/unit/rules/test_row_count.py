from __future__ import annotations

from sentinel.domain import RuleConfig
from sentinel.rules.row_count import RowCountRule
from tests.unit.doubles import FakeDataSource


def _rule_config(name: str = "row_count") -> RuleConfig:
    return RuleConfig.model_validate(
        {
            "name": name,
            "type": "row_count",
            "threshold": {"strategy": "static", "min": 1},
        }
    )


def test_metric_value_equals_the_row_count() -> None:
    source = FakeDataSource(rows=[{"id": 1}, {"id": 2}, {"id": 3}])
    metric = RowCountRule().compute(source, _rule_config())
    assert metric.value == 3.0


def test_empty_dataset_gives_zero() -> None:
    source = FakeDataSource(rows=[])
    metric = RowCountRule().compute(source, _rule_config())
    assert metric.value == 0.0


def test_metric_name_comes_from_the_configs_declared_name_not_the_rule_type() -> None:
    source = FakeDataSource(rows=[{"id": 1}])
    metric = RowCountRule().compute(source, _rule_config(name="orders_row_count_check"))
    assert metric.metric_name == "orders_row_count_check"


def test_row_count_rule_registers_itself_under_row_count() -> None:
    assert RowCountRule.rule_type == "row_count"
