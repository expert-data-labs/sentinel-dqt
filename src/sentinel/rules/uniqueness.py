"""UniquenessRule: how many rows in a column are duplicates.

Reports a count, not a rate — a straightforward reading of the PRD's
"Uniqueness" check and of the existing orders.yaml fixture, whose
threshold (``max: 0``) is written against a count of offending rows, the
same shape row_count and null_rate's thresholds already take.

Nulls are deliberately excluded from the duplicate arithmetic:
``distinct_count`` already excludes them per its own documented contract
(``DataSource.distinct_count``), and "are two nulls duplicates of each
other" is a null-rate question, not a uniqueness one — folding it in here
would make this one rule quietly do two jobs. The duplicate count is
therefore computed over non-null values only:

    duplicates = (row_count - null_count) - distinct_count

i.e. non-null rows minus how many distinct non-null values they represent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

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
            computed_at=datetime.now(UTC),
        )
