"""NullRateRule: fraction of rows where a column is null.

An empty dataset reports 0.0 instead of dividing by zero.
"""

from __future__ import annotations

from typing import ClassVar

from sentinel import clock
from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.registry import register_rule


@register_rule
class NullRateRule:
    """Measures the fraction of rows where ``config.column`` is null."""

    rule_type: ClassVar[str] = "null_rate"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        if config.column is None:
            raise RuleConfigError(
                f"null_rate rule {config.name!r} requires a 'column' field"
            )

        row_count = source.row_count()
        rate = 0.0 if row_count == 0 else source.null_count(config.column) / row_count

        return Metric(
            metric_name=config.name,
            value=rate,
            computed_at=clock.now(),
        )
