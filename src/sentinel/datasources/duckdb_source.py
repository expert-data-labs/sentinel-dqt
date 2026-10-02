"""DuckDBSource: reads a local CSV file through DuckDB.

Each method runs one query against ``read_csv_auto(path)``. Identifiers are
interpolated into SQL because placeholders only bind values; the path and column
names come from local config, not untrusted input.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import duckdb

from sentinel.datasources.registry import register_data_source

_DUCKDB_INTEGER_TYPES = {
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
}
_DUCKDB_FLOAT_TYPES = {"FLOAT", "DOUBLE", "REAL"}
_DUCKDB_STRING_TYPES = {"VARCHAR", "CHAR", "TEXT", "BPCHAR"}


def _canonical_type(duckdb_type: str) -> str:
    """Map a DuckDB type (from DESCRIBE) to a canonical type.

    DECIMAL and TIMESTAMP match by prefix (they take parameters). Unrecognized
    types map to "unknown".
    """
    normalized = duckdb_type.upper()
    if normalized.startswith("DECIMAL"):
        return "decimal"
    if normalized.startswith("TIMESTAMP"):
        return "timestamp"
    if normalized in _DUCKDB_STRING_TYPES:
        return "string"
    if normalized in _DUCKDB_INTEGER_TYPES:
        return "integer"
    if normalized in _DUCKDB_FLOAT_TYPES:
        return "float"
    if normalized == "BOOLEAN":
        return "boolean"
    if normalized == "DATE":
        return "date"
    return "unknown"


def _as_utc(value: Any) -> Any:
    """Return datetimes as UTC (naive ones are assumed UTC); pass other values
    through.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value


@register_data_source
class DuckDBSource:
    """Reads one CSV file. ``config_reference`` is the file path.

    A missing file surfaces as DuckDB's own error on the first query.
    """

    source_type: ClassVar[str] = "duckdb"

    def __init__(self, config_reference: str | None) -> None:
        if config_reference is None:
            raise ValueError(
                "DuckDBSource requires a Dataset with config_reference set "
                "to a CSV file path"
            )
        self._path = config_reference
        self._conn = duckdb.connect(":memory:")

    def _scalar(self, query: str) -> Any:
        row = self._conn.execute(query).fetchone()
        assert row is not None  # an aggregate query always returns exactly one row
        return row[0]

    def _source(self) -> str:
        return f"read_csv_auto('{self._path}')"

    def row_count(self) -> int:
        return int(self._scalar(f"SELECT count(*) FROM {self._source()}"))

    def null_count(self, column: str) -> int:
        return int(
            self._scalar(f'SELECT count(*) FROM {self._source()} WHERE "{column}" IS NULL')
        )

    def distinct_count(self, column: str) -> int:
        return int(self._scalar(f'SELECT count(DISTINCT "{column}") FROM {self._source()}'))

    def max_value(self, column: str) -> Any:
        return _as_utc(self._scalar(f'SELECT max("{column}") FROM {self._source()}'))

    def columns(self) -> dict[str, str]:
        rows = self._conn.execute(f"DESCRIBE SELECT * FROM {self._source()}").fetchall()
        return {row[0]: _canonical_type(row[1]) for row in rows}
