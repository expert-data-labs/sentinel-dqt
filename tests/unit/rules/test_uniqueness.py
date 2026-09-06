from __future__ import annotations

import pytest

from sentinel.domain import RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.uniqueness import UniquenessRule
from tests.unit.doubles import FakeDataSource


def _rule_config(column: str | None = "order_id") -> RuleConfig:
    data: dict[str, object] = {
        "name": "unique_order_id",
        "type": "uniqueness",
        "threshold": {"strategy": "static", "max": 0},
    }
    if column is not None:
        data["column"] = column
    return RuleConfig.model_validate(data)


def test_no_duplicates_gives_zero() -> None:
    source = FakeDataSource(rows=[{"order_id": 1}, {"order_id": 2}, {"order_id": 3}])
    metric = UniquenessRule().compute(source, _rule_config())
    assert metric.value == 0.0


def test_some_duplicates_are_counted() -> None:
    source = FakeDataSource(
        rows=[{"order_id": 1}, {"order_id": 1}, {"order_id": 2}, {"order_id": 3}]
    )
    metric = UniquenessRule().compute(source, _rule_config())
    # one extra occurrence of order_id=1 is the one duplicate
    assert metric.value == 1.0


def test_all_null_column_gives_zero_duplicates_not_row_count() -> None:
    source = FakeDataSource(rows=[{"order_id": None}, {"order_id": None}, {"order_id": None}])
    metric = UniquenessRule().compute(source, _rule_config())
    assert metric.value == 0.0


def test_empty_dataset_gives_zero() -> None:
    source = FakeDataSource(rows=[])
    metric = UniquenessRule().compute(source, _rule_config())
    assert metric.value == 0.0


def test_missing_column_raises_rule_config_error() -> None:
    source = FakeDataSource(rows=[{"order_id": 1}])
    with pytest.raises(RuleConfigError, match="column"):
        UniquenessRule().compute(source, _rule_config(column=None))
