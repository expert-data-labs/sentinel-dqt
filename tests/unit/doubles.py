"""Shared test doubles for Sentinel's unit tests.

FakeDataSource is an in-memory stand-in for the DataSource Protocol, built
from a list of row dicts, so rule/orchestration tests don't need a real
DuckDB connection. DummyRule is a Rule that returns a fixed Metric
regardless of input; DummyThresholdStrategy is a ThresholdStrategy that
returns a fixed verdict regardless of input. Both dummies exist to test
their registries and the orchestrator's control flow in isolation from any
real rule or threshold logic. FakeHistorySource (Milestone 4) is the same
idea applied to HistoricalMetricsSource: an in-memory stand-in so a
strategy or orchestrator test can control exactly what history is "on
record" without touching persistence.

FakeFailureHistorySource (Milestone 5) is the same idea again, applied to
FailureHistorySource: an in-memory stand-in so a frequency/confidence/
prioritizer test can control exactly what outcome history is "on record"
without touching persistence.

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

_PYTHON_TYPE_TO_CANONICAL: dict[type, str] = {
    str: "string",
    bool: "boolean",  # checked before int below — bool is an int subclass
    int: "integer",
    float: "float",
    datetime: "timestamp",
}


def _canonical_type_of(value: Any) -> str:
    for python_type, canonical in _PYTHON_TYPE_TO_CANONICAL.items():
        if isinstance(value, python_type):
            return canonical
    return "unknown"


@dataclass
class FakeDataSource:
    """An in-memory DataSource over a list of row dicts.

    Mirrors the edge-case contracts documented on DataSource itself: an
    empty ``rows`` list behaves like an empty dataset, and a column whose
    values are all ``None`` behaves like an all-null column.

    ``source_type`` is a ClassVar, not something instances vary — this
    double isn't resolved through the registry anywhere, but it still needs
    the attribute to structurally satisfy the DataSource Protocol wherever
    a test passes one in as a ``source: DataSource`` argument.
    """

    source_type: ClassVar[str] = "fake"

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

    def columns(self) -> dict[str, str]:
        """Infers each column's canonical type from the first non-null
        value seen for it, across all rows (a plain in-memory row list has
        no separate declared schema to read, unlike a real CSV/table).
        Column order follows first-appearance order across the rows,
        mirroring how a real header row would order them. A column every
        row leaves null gives ``"unknown"`` — there's no value to infer a
        type from, same reasoning ``max_value`` already applies to an
        all-null column returning ``None`` rather than guessing.
        """
        types: dict[str, str] = {}
        for row in self.rows:
            for column, value in row.items():
                if column not in types:
                    types[column] = "unknown"
                if value is not None and types[column] == "unknown":
                    types[column] = _canonical_type_of(value)
        return types


class DummyRule:
    """A Rule that ignores its inputs and returns a fixed value.

    Useful for testing the registry and the orchestrator's wiring without
    any real measurement logic in the way.
    """

    rule_type: ClassVar[str] = "dummy"

    def __init__(self, value: float = 1.0) -> None:
        self._value = value

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        return Metric(metric_name=config.name, value=self._value, computed_at=datetime.now(UTC))


class DummyThresholdStrategy:
    """A ThresholdStrategy that ignores its inputs and returns a fixed
    verdict. Useful for testing the registry and the orchestrator's wiring
    without any real evaluation logic."""

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


@dataclass
class FakeHistorySource:
    """An in-memory HistoricalMetricsSource, keyed by ``(dataset_id,
    metric_name)`` (see sentinel.thresholds.history for the real
    Protocol).

    Lets a test hand an orchestrator or a strategy exactly the history it
    wants to exercise, without standing up any persistence — the same
    role FakeDataSource plays for DataSource. An unrecognized key answers
    with an empty tuple, matching HistoricalMetricsSource's own contract
    that "no history yet" is an ordinary answer, not an error.
    """

    history: Mapping[tuple[str, str], Sequence[Metric]] = field(default_factory=dict)

    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]:
        return self.history.get((dataset_id, metric_name), ())


@dataclass
class FakeFailureHistorySource:
    """An in-memory FailureHistorySource, keyed by ``(dataset_id,
    metric_name)`` (see sentinel.prioritization.history for the real
    Protocol).

    Same role FakeHistorySource plays for HistoricalMetricsSource, applied
    to outcome (Status) history instead of Metric-value history. An
    unrecognized key answers with an empty tuple, matching
    FailureHistorySource's own "no history yet is ordinary" contract.
    """

    outcomes: Mapping[tuple[str, str], Sequence[Status]] = field(default_factory=dict)

    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        return self.outcomes.get((dataset_id, metric_name), ())
