"""DuckDBSource: reads data files through DuckDB.

``config_reference`` is a path or glob to CSV, Parquet or JSON files, locally
or on S3 (``s3://bucket/orders/*.parquet``). The reader is chosen by file
extension. S3 credentials come from the standard AWS credential chain
(environment variables, ``~/.aws``, instance roles).
"""

from __future__ import annotations

from typing import Any, ClassVar

import duckdb

from sentinel.datasources._common import ConfigReferenceError
from sentinel.datasources.registry import register_data_source
from sentinel.datasources.sql_base import SqlDataSource

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
_DUCKDB_STRING_TYPES = {"VARCHAR", "CHAR", "TEXT", "BPCHAR", "UUID"}

# File extension -> DuckDB table function.
_READERS = {
    ".csv": "read_csv_auto",
    ".tsv": "read_csv_auto",
    ".txt": "read_csv_auto",
    ".parquet": "read_parquet",
    ".json": "read_json_auto",
    ".jsonl": "read_json_auto",
    ".ndjson": "read_json_auto",
}
_REMOTE_PREFIXES = ("s3://", "s3a://", "s3n://")


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


def _reader_for(path: str) -> str:
    """The DuckDB table function for ``path``, chosen by extension (ignoring .gz etc.)."""
    name = path.lower()
    for compression in (".gz", ".zst"):
        name = name.removesuffix(compression)
    for extension, reader in _READERS.items():
        if name.endswith(extension):
            return reader
    supported = ", ".join(sorted(_READERS))
    raise ConfigReferenceError(
        f"Can't tell the file format of {path!r}; use one of these extensions: {supported}"
    )


@register_data_source
class DuckDBSource(SqlDataSource):
    """Reads CSV, Parquet or JSON files (local or S3). Each query re-reads the files.

    A missing file surfaces as DuckDB's own error on the first query.
    """

    source_type: ClassVar[str] = "duckdb"

    def __init__(self, config_reference: str | None) -> None:
        if config_reference is None:
            raise ValueError(
                "DuckDBSource requires a Dataset with config_reference set to a file path, "
                "e.g. 'data/orders.csv' or 's3://bucket/orders/*.parquet'"
            )
        self._path = config_reference
        self._reader = _reader_for(config_reference)
        self._conn = duckdb.connect(":memory:")
        if config_reference.startswith(_REMOTE_PREFIXES):
            # httpfs and aws extensions are auto-installed on first use.
            self._conn.execute(
                "CREATE OR REPLACE SECRET sentinel_s3 (TYPE s3, PROVIDER credential_chain)"
            )

    def _table(self) -> str:
        path = self._path.replace("'", "''")
        return f"{self._reader}('{path}')"

    def _scalar(self, query: str) -> Any:
        row = self._conn.execute(query).fetchone()
        assert row is not None  # aggregates always return one row
        return row[0]

    def columns(self) -> dict[str, str]:
        rows = self._conn.execute(f"DESCRIBE SELECT * FROM {self._table()}").fetchall()
        return {row[0]: _canonical_type(row[1]) for row in rows}
