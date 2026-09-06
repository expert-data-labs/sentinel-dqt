"""RowCountRule: the simplest possible Rule (FR-03) — total row count.

No column is required; row count is a property of the dataset as a whole,
not of any one field. This is deliberately the thinnest Rule
implementation Milestone 1 has, and its main job beyond being useful on
its own is proving the registration path (``@register_rule`` ->
``sentinel.registration.register_all()`` -> ``get_rule("row_count")``)
works end to end with a real, non-dummy rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules.registry import register_rule


@register_rule
class RowCountRule:
    """Measures the total number of rows in a dataset.

    ``metric_name`` comes from ``config.name`` — the rule's own declared
    name in the policy — not from ``rule_type``. Every Milestone 1 rule
    follows this same convention (established by ``DummyRule`` in
    Milestone 0's test doubles): it's what lets two instances of the same
    rule type (rare for row count, common for ``null_rate``/``uniqueness``
    on different columns) produce distinguishable QualityEvents without
    ``Metric`` needing a separate dimensions field.
    """

    rule_type: ClassVar[str] = "row_count"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        return Metric(
            metric_name=config.name,
            value=float(source.row_count()),
            computed_at=datetime.now(UTC),
        )
