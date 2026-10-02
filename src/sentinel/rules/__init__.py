"""Rule engine: registered quality checks.

A Rule computes a Metric from a DataSource. Pass/fail is decided by a
ThresholdStrategy, not by the rule.
"""

from sentinel.rules.base import Rule, RuleConfigError
from sentinel.rules.registry import RuleNotRegisteredError, get_rule, register_rule

__all__ = ["Rule", "RuleConfigError", "RuleNotRegisteredError", "get_rule", "register_rule"]
