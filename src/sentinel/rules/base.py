"""The Rule interface (FR-03): compute one measurement from a DataSource.

A Rule never decides pass/fail — it only measures. Judging whether a
Metric is acceptable is a ThresholdStrategy's job (sentinel.thresholds),
evaluated separately by the orchestrator. Keeping these apart means a new
Rule never has to know anything about thresholds, and a new
ThresholdStrategy never has to know anything about any specific Rule.
"""

from __future__ import annotations

from typing import ClassVar, Protocol

from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig


class Rule(Protocol):
    """A registered, reusable quality check (FR-03).

    ``rule_type`` is the string a RuleConfig's ``type`` field names this
    rule by, and the key the registry (sentinel.rules.registry) looks it up
    under — it's a ClassVar, not an instance attribute, because it
    identifies the *kind* of rule, the same for every instance.
    """

    rule_type: ClassVar[str]

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        """Compute one measurement for this rule against ``source``.

        ``config`` is this rule's own declaration from the policy (its
        ``column``, if any, and whatever else the concrete rule needs) —
        not the whole Policy. Implementations should raise a clear error if
        a field they require (e.g. ``column`` for a null-rate check) is
        missing, rather than failing obscurely partway through.
        """
        ...
