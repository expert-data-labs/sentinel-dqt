"""The Rule Engine: reusable, registered implementations of quality checks.

A Rule computes a Metric from a DataSource. It never decides pass/fail —
that judgment belongs to a ThresholdStrategy (see sentinel.thresholds).
"""

from sentinel.rules.base import Rule
from sentinel.rules.registry import RuleNotRegisteredError, get_rule, register_rule

__all__ = ["Rule", "RuleNotRegisteredError", "get_rule", "register_rule"]
