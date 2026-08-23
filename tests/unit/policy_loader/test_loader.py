from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.policy_loader import PolicyLoadError, load_policy

FIXTURES = Path(__file__).parents[2] / "fixtures" / "policies"


def test_loads_the_prd_example_policy() -> None:
    policy = load_policy(FIXTURES / "orders.yaml")

    assert policy.dataset == "orders"
    assert [rule.name for rule in policy.rules] == [
        "row_count",
        "customer_id_not_null",
        "unique_order_id",
        "freshness",
    ]

    row_count_rule = policy.rules[0]
    assert row_count_rule.rule_type == "volume"
    assert row_count_rule.threshold.strategy == "static"
    assert row_count_rule.threshold.params == {"min": 1000}

    freshness_rule = policy.rules[3]
    assert freshness_rule.column == "updated_at"
    assert freshness_rule.threshold.params == {"max_delay_minutes": 60}


def test_missing_file_raises_policy_load_error() -> None:
    with pytest.raises(PolicyLoadError):
        load_policy(FIXTURES / "does_not_exist.yaml")


def test_invalid_yaml_syntax_raises_policy_load_error() -> None:
    with pytest.raises(PolicyLoadError):
        load_policy(FIXTURES / "malformed_syntax.yaml")


def test_schema_violation_raises_policy_load_error() -> None:
    with pytest.raises(PolicyLoadError):
        load_policy(FIXTURES / "malformed_schema.yaml")
