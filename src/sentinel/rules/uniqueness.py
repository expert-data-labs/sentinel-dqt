"""UniquenessRule: number of duplicate values in a column.

Nulls are ignored (that's what null_rate checks):

    duplicates = (row_count - null_count) - distinct_count
"""

from __future__ import annotations

from typing import ClassVar

from sentinel import clock
from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.registry import register_rule


@register_rule
class UniquenessRule:
    """Measures the number of duplicate (non-null) values in a column."""

    rule_type: ClassVar[str] = "uniqueness"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        if config.column is None:
            raise RuleConfigError(
                f"uniqueness rule {config.name!r} requires a 'column' field"
            )

        non_null_count = source.row_count() - source.null_count(config.column)
        duplicate_count = non_null_count - source.distinct_count(config.column)

        return Metric(
            metric_name=config.name,
            value=float(duplicate_count),
            computed_at=clock.now(),
        )
