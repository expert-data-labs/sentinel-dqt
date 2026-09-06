from __future__ import annotations

import pytest

from sentinel.domain import RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.null_rate import NullRateRule
from tests.unit.doubles import FakeDataSource


def _rule_config(column: str | None = "customer_id") -> RuleConfig:
    data: dict[str, object] = {
        "name": "customer_id_not_null",
        "type": "null_rate",
        "threshold": {"strategy": "static", "max": 0.01},
    }
    if column is not None:
        data["column"] = column
    return RuleConfig.model_validate(data)


def test_mixed_nulls_gives_the_correct_fraction() -> None:
    source = FakeDataSource(
        rows=[
            {"customer_id": 1},
            {"customer_id": None},
            {"customer_id": 3},
            {"customer_id": None},
        ]
    )
    metric = NullRateRule().compute(source, _rule_config())
    assert metric.value == 0.5


def test_all_null_column_gives_rate_of_one() -> None:
    source = FakeDataSource(rows=[{"customer_id": None}, {"customer_id": None}])
    metric = NullRateRule().compute(source, _rule_config())
    assert metric.value == 1.0


def test_no_nulls_gives_rate_of_zero() -> None:
    source = FakeDataSource(rows=[{"customer_id": 1}, {"customer_id": 2}])
    metric = NullRateRule().compute(source, _rule_config())
    assert metric.value == 0.0


def test_empty_dataset_gives_rate_of_zero_not_a_division_error() -> None:
    source = FakeDataSource(rows=[])
    metric = NullRateRule().compute(source, _rule_config())
    assert metric.value == 0.0


def test_missing_column_raises_rule_config_error() -> None:
    source = FakeDataSource(rows=[{"customer_id": 1}])
    with pytest.raises(RuleConfigError, match="column"):
        NullRateRule().compute(source, _rule_config(column=None))
