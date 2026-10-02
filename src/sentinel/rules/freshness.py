"""FreshnessRule: minutes since the latest timestamp in a column."""

from __future__ import annotations

from typing import ClassVar

from sentinel import clock
from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.registry import register_rule


@register_rule
class FreshnessRule:
    """Minutes elapsed since ``max_value(config.column)``.

    ``max_value`` returns timezone-aware UTC, so plain subtraction is safe.

    - Empty table or all-null column: ``inf`` (always fails a ``max`` threshold).
    - Null timestamps are ignored.
    - Future timestamps give a negative value (not clamped), so a ``min: 0``
      threshold can catch clock skew.
    """

    rule_type: ClassVar[str] = "freshness"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        if config.column is None:
            raise RuleConfigError(f"freshness rule {config.name!r} requires a 'column' field")

        latest = source.max_value(config.column)
        freshness_minutes = (
            float("inf")
            if latest is None
            else (clock.now() - latest).total_seconds() / 60.0
        )

        return Metric(
            metric_name=config.name,
            value=freshness_minutes,
            computed_at=clock.now(),
        )
