"""These tests exercise FakeDataSource, but their real job is to pin down
DataSource's documented edge-case contracts (empty dataset, all-null
column) in executable form, and to prove — via the DataSource-typed
variable each test assigns through — that FakeDataSource satisfies the
Protocol structurally (checked by mypy, not at runtime; DataSource has no
@runtime_checkable marker)."""

from __future__ import annotations

from datetime import UTC, datetime

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


def test_columns_on_empty_dataset_is_an_empty_mapping() -> None:
    source: DataSource = FakeDataSource(rows=[])
    assert source.columns() == {}


def test_columns_infers_canonical_type_from_first_non_null_value() -> None:
    source: DataSource = FakeDataSource(
        rows=[
            {
                "order_id": 1001,
                "customer_id": "C001",
                "order_total": 59.99,
                "is_gift": True,
                "updated_at": datetime(2026, 8, 23, tzinfo=UTC),
            }
        ]
    )
    assert source.columns() == {
        "order_id": "integer",
        "customer_id": "string",
        "order_total": "float",
        "is_gift": "boolean",
        "updated_at": "timestamp",
    }


def test_columns_on_all_null_column_is_unknown_not_a_guess() -> None:
    source: DataSource = FakeDataSource(rows=[{"notes": None}, {"notes": None}])
    assert source.columns() == {"notes": "unknown"}


def test_columns_preserves_first_appearance_order() -> None:
    source: DataSource = FakeDataSource(rows=[{"b": 1, "a": 2}])
    assert list(source.columns()) == ["b", "a"]
