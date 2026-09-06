"""FreshnessRule: how many minutes old a dataset is, measured from a
timestamp column.

Reuses StaticThresholdStrategy exactly as it already exists (e.g. a policy
sets ``max: 60`` on this rule's threshold) -- this rule does not decide
"stale" vs. "fresh" itself. See sentinel.rules.base for why a Rule never
judges its own Metric; freshness is not a special case of that principle,
just another measurement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from sentinel.datasources.base import DataSource
from sentinel.domain import Metric, RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.registry import register_rule


@register_rule
class FreshnessRule:
    """Measures how many minutes have elapsed since the most recent value
    in ``config.column`` (expected to hold timestamps).

    Relies entirely on ``DataSource.max_value()``'s Milestone 3 contract:
    the returned datetime is always timezone-aware UTC, so this rule can do
    plain ``datetime.now(UTC) - max_value`` arithmetic with no
    backend-specific timezone handling of its own -- see the contract note
    on ``DataSource.max_value``.

    Edge cases (see docs/architecture/0004-milestone-3-architecture.md
    Part 4 for the full discussion this rule implements):

    - Empty dataset or an all-null column: ``max_value`` returns ``None``,
      and this rule reports ``float("inf")`` minutes -- "infinitely stale"
      rather than raising or inventing an arbitrary sentinel value, so a
      ``StaticThresholdStrategy`` ``max: N`` threshold fails it exactly
      like any other too-old dataset, with no special case needed anywhere
      downstream.
    - Some null timestamps: ``max_value`` already ignores nulls when
      computing the max, so this rule sees the same value it would if
      those rows didn't exist.
    - A timestamp in the future: reported as a *negative* number of
      minutes, not clamped to zero. Clamping would be a judgment call
      ("negative freshness doesn't make sense, so treat it as fresh") that
      belongs to a ThresholdStrategy, not this rule -- and reporting the
      true value lets a policy author catch clock-skew data with a
      ``min: 0`` threshold if they choose to.
    """

    rule_type: ClassVar[str] = "freshness"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        if config.column is None:
            raise RuleConfigError(f"freshness rule {config.name!r} requires a 'column' field")

        latest = source.max_value(config.column)
        freshness_minutes = (
            float("inf")
            if latest is None
            else (datetime.now(UTC) - latest).total_seconds() / 60.0
        )

        return Metric(
            metric_name=config.name,
            value=freshness_minutes,
            computed_at=datetime.now(UTC),
        )
