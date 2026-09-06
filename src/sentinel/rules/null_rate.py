"""NullRateRule: the fraction of rows in a column that are null.

Unlike row count, this rule can't avoid needing a column — "null rate of
what?" has no dataset-wide answer. On an empty dataset it reports 0.0
rather than raising a ZeroDivisionError: DataSource's own contract already
treats an empty dataset as ordinary, not exceptional (row_count() and
null_count() both simply return 0), so "no rows to violate the rule" is
the reading that keeps an empty table a boring PASS/FAIL like any other,
instead of a special always-erroring case.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

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
            computed_at=datetime.now(UTC),
        )
