"""Rule interface: compute one Metric from a DataSource.

Rules only measure. A ThresholdStrategy decides pass/fail.
"""

from __future__ import annotations

from typing import ClassVar, Protocol

from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig


class RuleConfigError(Exception):
    """A RuleConfig is missing a field its rule needs (e.g. ``column``).

    Raised when the rule runs, since only the rule knows what it requires.
    """


class Rule(Protocol):
    """A registered quality check.

    ``rule_type`` is the policy's ``type`` value and the registry key.
    """

    rule_type: ClassVar[str]

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        """Measure ``source`` for this rule. Raise RuleConfigError if config is
        incomplete.
        """
        ...
