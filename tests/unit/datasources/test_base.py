"""These tests exercise FakeDataSource, but their real job is to pin down
DataSource's documented edge-case contracts (empty dataset, all-null
column) in executable form, and to prove — via the DataSource-typed
variable each test assigns through — that FakeDataSource satisfies the
Protocol structurally (checked by mypy, not at runtime; DataSource has no
@runtime_checkable marker)."""

from __future__ import annotations

from sentinel.datasources import DataSource
from tests.unit.doubles import FakeDataSource


def test_row_count_on_empty_dataset() -> None:
    source: DataSource = FakeDataSource(rows=[])
    assert source.row_count() == 0


def test_null_count_on_empty_dataset() -> None:
    source: DataSource = FakeDataSource(rows=[])
    assert source.null_count("customer_id") == 0


def test_null_count_when_every_value_is_null() -> None:
    source: DataSource = FakeDataSource(rows=[{"customer_id": None}, {"customer_id": None}])
    assert source.null_count("customer_id") == source.row_count() == 2


def test_distinct_count_on_empty_dataset() -> None:
    source: DataSource = FakeDataSource(rows=[])
    assert source.distinct_count("order_id") == 0


def test_distinct_count_excludes_nulls() -> None:
    source: DataSource = FakeDataSource(
        rows=[{"order_id": "a"}, {"order_id": "a"}, {"order_id": None}]
    )
    assert source.distinct_count("order_id") == 1


def test_distinct_count_on_all_null_column_is_zero_not_one() -> None:
    source: DataSource = FakeDataSource(rows=[{"order_id": None}, {"order_id": None}])
    assert source.distinct_count("order_id") == 0


def test_max_value_on_empty_dataset_is_none() -> None:
    source: DataSource = FakeDataSource(rows=[])
    assert source.max_value("updated_at") is None


def test_max_value_returns_the_largest_non_null_value() -> None:
    source: DataSource = FakeDataSource(rows=[{"x": 1}, {"x": 3}, {"x": None}, {"x": 2}])
    assert source.max_value("x") == 3
