from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel.domain import Policy, RuleConfig, Severity, ThresholdConfig


def test_threshold_config_collects_unknown_keys_into_params() -> None:
    threshold = ThresholdConfig.model_validate({"strategy": "static", "min": 1000})
    assert threshold.strategy == "static"
    assert threshold.params == {"min": 1000}


def test_threshold_config_is_frozen() -> None:
    threshold = ThresholdConfig(strategy="static", params={"min": 1000})
    with pytest.raises(ValidationError):
        threshold.strategy = "percentage_deviation"  # type: ignore[misc]


def test_rule_config_accepts_yaml_style_type_key() -> None:
    rule = RuleConfig.model_validate(
        {
            "name": "row_count",
            "type": "volume",
            "threshold": {"strategy": "static", "min": 1000},
        }
    )
    assert rule.rule_type == "volume"
    assert rule.column is None
    assert rule.expected_schema is None
    assert rule.severity is Severity.WARNING
    assert rule.blocking is True


def test_rule_config_column_and_severity_are_settable() -> None:
    rule = RuleConfig.model_validate(
        {
            "name": "customer_id_not_null",
            "type": "null_rate",
            "column": "customer_id",
            "severity": "critical",
            "blocking": False,
            "threshold": {"strategy": "static", "max": 0.01},
        }
    )
    assert rule.column == "customer_id"
    assert rule.severity is Severity.CRITICAL
    assert rule.blocking is False


def test_rule_config_requires_threshold() -> None:
    with pytest.raises(ValidationError):
        RuleConfig.model_validate({"name": "row_count", "type": "volume"})


def test_rule_config_expected_schema_is_settable() -> None:
    """Milestone 3: the schema validation rule's own YAML shape —
    ``expected_schema: {column: type, ...}``."""
    rule = RuleConfig.model_validate(
        {
            "name": "orders_schema",
            "type": "schema",
            "expected_schema": {
                "order_id": "string",
                "customer_id": "string",
                "amount": "decimal",
                "created_at": "timestamp",
            },
            "threshold": {"strategy": "static", "max": 0},
        }
    )
    assert rule.expected_schema == {
        "order_id": "string",
        "customer_id": "string",
        "amount": "decimal",
        "created_at": "timestamp",
    }


def test_rule_config_expected_schema_rejects_non_string_values() -> None:
    """A pydantic field, so a malformed expected_schema fails at
    policy-load time — not silently accepted and only discovered when a
    Rule tries to use it."""
    with pytest.raises(ValidationError):
        RuleConfig.model_validate(
            {
                "name": "orders_schema",
                "type": "schema",
                "expected_schema": {"order_id": 123},
                "threshold": {"strategy": "static", "max": 0},
            }
        )


def test_policy_requires_at_least_one_rule() -> None:
    with pytest.raises(ValidationError):
        Policy.model_validate({"dataset": "orders", "rules": []})


def test_policy_defaults_version_when_not_specified() -> None:
    policy = Policy.model_validate(
        {
            "dataset": "orders",
            "rules": [
                {
                    "name": "row_count",
                    "type": "volume",
                    "threshold": {"strategy": "static", "min": 1000},
                }
            ],
        }
    )
    assert policy.version == "unversioned"
    assert len(policy.rules) == 1


def test_policy_is_frozen() -> None:
    policy = Policy.model_validate(
        {
            "dataset": "orders",
            "rules": [
                {
                    "name": "row_count",
                    "type": "volume",
                    "threshold": {"strategy": "static", "min": 1000},
                }
            ],
        }
    )
    with pytest.raises(ValidationError):
        policy.dataset = "customers"  # type: ignore[misc]
