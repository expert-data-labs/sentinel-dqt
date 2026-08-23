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
