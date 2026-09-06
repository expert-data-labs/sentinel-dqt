"""SchemaValidationRule: how many structural differences exist between a
dataset's actual columns and a policy's expected schema.

Reuses StaticThresholdStrategy exactly as it already exists (typically
``max: 0`` -- any difference at all is a schema violation) -- this rule
does not decide "passes schema validation" itself, matching every other
Rule in Sentinel; see sentinel.rules.base.

``Metric.value`` is the *count* of differences (missing + unexpected +
type-mismatched columns, combined) so ``StaticThresholdStrategy`` can keep
evaluating it exactly like any other numeric metric. *Which* columns
differ, and how, is carried separately in ``Metric.details`` as a
JSON-encoded structured diff -- see sentinel.domain.metric for why
``details`` exists and why it's a JSON string rather than a nested field.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import ClassVar

from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.registry import register_rule


@register_rule
class SchemaValidationRule:
    """Compares ``source.columns()`` against ``config.expected_schema``
    and measures how many columns differ.

    Three kinds of difference, each independent of the others:

    - **Missing**: a column ``expected_schema`` names that ``source``
      doesn't have.
    - **Unexpected**: a column ``source`` has that ``expected_schema``
      doesn't name.
    - **Type mismatch**: a column both sides agree exists, but whose
      canonical type (see ``DataSource.columns()``) doesn't match what
      ``expected_schema`` declares for it.

    All three are counted into ``Metric.value``; all three are named, with
    their concrete values, in ``Metric.details`` as JSON:
    ``{"missing_columns": [...], "unexpected_columns": [...],
    "type_mismatches": {"col": {"expected": ..., "actual": ...}, ...}}``.
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
            computed_at=datetime.now(UTC),
            details=details,
        )
