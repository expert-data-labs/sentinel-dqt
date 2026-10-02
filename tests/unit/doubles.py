"""In-memory test doubles shared by unit tests.

- FakeDataSource: DataSource over a list of row dicts
- DummyRule / DummyThresholdStrategy: return fixed results
- FakeHistorySource / FakeFailureHistorySource: canned history
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
    """In-memory DataSource over a list of row dicts.

    Follows DataSource's empty-dataset and all-null rules.
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
        """Infer each column's type from its first non-null value.

        Order follows first appearance. All-null columns are "unknown".
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
    """Rule that ignores its inputs and returns a fixed value."""

    rule_type: ClassVar[str] = "dummy"

    def __init__(self, value: float = 1.0) -> None:
        self._value = value

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        return Metric(metric_name=config.name, value=self._value, computed_at=datetime.now(UTC))


class DummyThresholdStrategy:
    """ThresholdStrategy that ignores its inputs and returns a fixed verdict."""

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
    """In-memory HistoricalMetricsSource keyed by (dataset_id, metric_name).
    Unknown keys return ().
    """

    history: Mapping[tuple[str, str], Sequence[Metric]] = field(default_factory=dict)

    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]:
        return self.history.get((dataset_id, metric_name), ())


@dataclass
class FakeFailureHistorySource:
    """In-memory FailureHistorySource keyed by (dataset_id, metric_name). Unknown
    keys return ().
    """

    outcomes: Mapping[tuple[str, str], Sequence[Status]] = field(default_factory=dict)

    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        return self.outcomes.get((dataset_id, metric_name), ())
