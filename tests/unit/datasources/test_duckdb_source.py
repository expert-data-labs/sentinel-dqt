"""Unlike the other DataSource tests in this package (test_base.py, which
exercises FakeDataSource), these tests exercise DuckDBSource directly
against real CSV files on disk — there's no meaningful way to test "does
this SQL actually do what the DataSource contract requires" without a
real DuckDB engine reading a real file. Instantiated directly, not
through get_data_source(); the registry mechanics are covered separately
in test_registry.py and test_registration.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.datasources.duckdb_source import DuckDBSource, _canonical_type


def _write_csv(tmp_path: Path, content: str) -> str:
    path = tmp_path / "data.csv"
    path.write_text(content)
    return str(path)


def test_row_count_and_distinct_count_with_no_nulls(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "id,name\n1,alice\n2,bob\n3,carol\n4,alice\n")
    source = DuckDBSource(path)

    assert source.row_count() == 4
    assert source.distinct_count("id") == 4
    assert source.distinct_count("name") == 3  # alice, bob, carol


def test_null_count_with_mixed_nulls(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "id,name,amount\n1,alice,10.5\n2,,20.0\n3,bob,\n4,alice,5.0\n")
    source = DuckDBSource(path)

    assert source.null_count("name") == 1
    assert source.null_count("amount") == 1
    assert source.distinct_count("name") == 2  # alice, bob — null excluded


def test_max_value_returns_the_largest_non_null_value(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "id,amount\n1,10.5\n2,20.0\n3,5.0\n")
    source = DuckDBSource(path)

    assert source.max_value("amount") == 20.0
    assert source.max_value("id") == 3


def test_all_null_column_gives_zero_distinct_and_none_max(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "id,name\n1,\n2,\n")
    source = DuckDBSource(path)

    assert source.null_count("name") == 2
    assert source.distinct_count("name") == 0  # not 1 — null isn't "a value"
    assert source.max_value("name") is None


def test_empty_dataset_gives_zero_for_every_count_and_none_for_max(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "id,name\n")
    source = DuckDBSource(path)

    assert source.row_count() == 0
    assert source.null_count("name") == 0
    assert source.distinct_count("name") == 0
    assert source.max_value("name") is None


def test_missing_config_reference_raises() -> None:
    with pytest.raises(ValueError, match="config_reference"):
        DuckDBSource(None)


def test_registers_itself_under_duckdb() -> None:
    assert DuckDBSource.source_type == "duckdb"


# --- Milestone 3: columns() -----------------------------------------------


def test_columns_maps_duckdb_types_to_the_canonical_vocabulary(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        "order_id,customer_id,order_total,updated_at\n"
        "1001,C001,59.99,2026-08-23T10:00:00\n"
        "1002,C002,19.50,2026-08-23T09:45:00\n",
    )
    source = DuckDBSource(path)
    columns = source.columns()

    assert columns["order_id"] == "integer"
    assert columns["customer_id"] == "string"
    assert columns["order_total"] == "float"
    assert columns["updated_at"] == "timestamp"


def test_columns_is_structural_and_works_on_an_empty_dataset(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "id,name\n")
    source = DuckDBSource(path)

    # 0 rows, but the header alone is enough for DuckDB to DESCRIBE it —
    # schema introspection needs no empty-dataset special case.
    assert set(source.columns()) == {"id", "name"}


@pytest.mark.parametrize(
    ("duckdb_type", "expected"),
    [
        ("VARCHAR", "string"),
        ("BIGINT", "integer"),
        ("INTEGER", "integer"),
        ("DOUBLE", "float"),
        ("DECIMAL(18,3)", "decimal"),
        ("BOOLEAN", "boolean"),
        ("DATE", "date"),
        ("TIMESTAMP", "timestamp"),
        ("TIMESTAMP WITH TIME ZONE", "timestamp"),
        ("BLOB", "unknown"),
    ],
)
def test_canonical_type_mapping(duckdb_type: str, expected: str) -> None:
    assert _canonical_type(duckdb_type) == expected


# --- Milestone 3: max_value's UTC contract for timestamp columns ----------


def test_max_value_on_a_timestamp_column_is_timezone_aware_utc(tmp_path: Path) -> None:
    """Pins down the DataSource.max_value contract (Part 3b of the
    architecture doc): whatever tzinfo DuckDB itself infers for a CSV
    timestamp column, the value this adapter hands back must be
    UTC-aware, never naive — a FreshnessRule computing
    ``datetime.now(UTC) - source.max_value(column)`` cannot safely handle
    "maybe naive, maybe not" on its own.
    """
    path = _write_csv(
        tmp_path,
        "id,updated_at\n1,2026-08-23T10:00:00\n2,2026-08-23T09:45:00\n",
    )
    source = DuckDBSource(path)

    latest = source.max_value("updated_at")

    assert latest.tzinfo is not None
    assert latest.utcoffset().total_seconds() == 0
    assert latest.hour == 10  # the naive wall-clock value, now stamped as UTC


def test_max_value_on_all_null_timestamp_column_is_still_none(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "id,updated_at\n1,\n2,\n")
    source = DuckDBSource(path)

    assert source.max_value("updated_at") is None
