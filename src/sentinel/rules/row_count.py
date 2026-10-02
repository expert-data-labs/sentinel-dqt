"""RowCountRule: total number of rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules.registry import register_rule


@register_rule
class RowCountRule:
    """Counts the rows in a dataset.

    ``metric_name`` is the rule's name from the policy (``config.name``), so two
    rules of the same type stay distinguishable. All rules follow this.
    """

    rule_type: ClassVar[str] = "row_count"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        return Metric(
            metric_name=config.name,
            value=float(source.row_count()),
            computed_at=datetime.now(UTC),
        )
