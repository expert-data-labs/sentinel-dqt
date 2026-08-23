"""Shared test doubles for Milestone 0's unit tests.

FakeDataSource is an in-memory stand-in for the DataSource Protocol, built
from a list of row dicts, so rule/orchestration tests don't need a real
DuckDB connection. DummyRule is a Rule that returns a fixed Metric
regardless of input; DummyThresholdStrategy is a ThresholdStrategy that
returns a fixed verdict regardless of input. Both dummies exist to test
their registries and, later, the orchestrator's control flow (Task 7) in
isolation from any real rule or threshold logic.

Not a conftest.py: these are plain importable classes, not pytest
fixtures — nothing here needs autouse injection, and being explicit about
which test imports which double is more readable than implicit fixture
magic for a handful of simple stand-ins.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from sentinel.datasources import DataSource
from sentinel.domain import Metric, RuleConfig, Status, ThresholdConfig, ThresholdResult


@dataclass
class FakeDataSource:
    """An in-memory DataSource over a list of row dicts.

    Mirrors the edge-case contracts documented on DataSource itself: an
    empty ``rows`` list behaves like an empty dataset, and a column whose
    values are all ``None`` behaves like an all-null column.
    """

    rows: Sequence[Mapping[str, Any]] = field(default_factory=list)

    def row_count(self) -> int:
        return len(self.rows)

    def null_count(self, column: str) -> int:
        return sum(1 for row in self.rows if row.get(column) is None)

    def distinct_count(self, column: str) -> int:
        return len({row[column] for row in self.rows if row.get(column) is not None})

    def max_value(self, column: str) -> Any:
        values = [row[column] for row in self.rows if row.get(column) is not None]
        return max(values) if values else None


class DummyRule:
    """A Rule that ignores its inputs and returns a fixed value.

    Useful for testing the registry (Task 4) and, later, the orchestrator's
    wiring (Task 7) without any real measurement logic in the way.
    """

    rule_type: ClassVar[str] = "dummy"

    def __init__(self, value: float = 1.0) -> None:
        self._value = value

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        return Metric(metric_name=config.name, value=self._value, computed_at=datetime.now(UTC))


class DummyThresholdStrategy:
    """A ThresholdStrategy that ignores its inputs and returns a fixed
    verdict. Useful for testing the registry (Task 5) and, later, the
    orchestrator's wiring (Task 7) without any real evaluation logic."""

    strategy_type: ClassVar[str] = "dummy"

    def __init__(self, status: Status = Status.PASS) -> None:
        self._status = status

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        return ThresholdResult(
            status=self._status,
            expected="dummy expectation",
            strategy_type=self.strategy_type,
        )
