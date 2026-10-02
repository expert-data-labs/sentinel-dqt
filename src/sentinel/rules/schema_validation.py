"""SchemaValidationRule: number of differences between actual and expected columns.

``Metric.value`` is the count, so a static threshold (usually ``max: 0``)
can judge it. ``Metric.details`` lists which columns differ, as JSON.
"""

from __future__ import annotations

import json
from typing import ClassVar

from sentinel import clock
from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.registry import register_rule


@register_rule
class SchemaValidationRule:
    """Compares ``source.columns()`` with ``config.expected_schema``.

    Counts three kinds of difference:

    - missing: expected but not present
    - unexpected: present but not expected
    - type mismatch: present on both sides with different types

    ``details`` JSON: ``{"missing_columns": [...], "unexpected_columns": [...],
    "type_mismatches": {"col": {"expected": ..., "actual": ...}}}``.
    """

    rule_type: ClassVar[str] = "schema"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        if config.expected_schema is None:
            raise RuleConfigError(
                f"schema rule {config.name!r} requires an 'expected_schema' field"
            )

        expected = config.expected_schema
        actual = source.columns()

        missing_columns = sorted(set(expected) - set(actual))
        unexpected_columns = sorted(set(actual) - set(expected))
        type_mismatches = {
            column: {"expected": expected[column], "actual": actual[column]}
            for column in sorted(set(expected) & set(actual))
            if expected[column] != actual[column]
        }

        difference_count = len(missing_columns) + len(unexpected_columns) + len(type_mismatches)

        details = json.dumps(
            {
                "missing_columns": missing_columns,
                "unexpected_columns": unexpected_columns,
                "type_mismatches": type_mismatches,
            }
        )

        return Metric(
            metric_name=config.name,
            value=float(difference_count),
            computed_at=clock.now(),
            details=details,
        )
