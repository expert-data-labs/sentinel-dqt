"""DuckDBSource: a DataSource adapter that queries a local CSV file
through DuckDB's SQL engine.

Pulled forward from Milestone 3's slot (Project_Milestones.md lists the
DuckDB adapter there) because Milestone 2's CLI had nothing to validate
against without a working adapter — see
docs/architecture/0003-milestone-2-architecture.md Part 2 for the full
reasoning. Milestone 3 extends this adapter rather than replacing it:
``columns()`` (schema introspection) and timezone-safe ``max_value`` are
new here, added once ``FreshnessRule``/``SchemaValidationRule`` actually
needed them — see docs/architecture/0004-milestone-3-architecture.md
Part 3.

Each DataSource method is one SQL query against ``read_csv_auto(path)`` —
the file is never loaded into an in-memory table Sentinel manages. This is
a different DuckDB connection from sentinel.persistence's own DuckDB-backed
store: this one queries the dataset *being validated*, ephemeral and
scoped to one instance; that one is Sentinel's durable operational
history. See docs/architecture/0003-milestone-2-architecture.md Part 3.

SQL here is built with plain string interpolation, not parameter binding
— DuckDB's placeholders bind *values*, not identifiers or table/file
sources, and both the file path and column names come from this
process's own trusted local config (a Dataset's ``config_reference``, a
RuleConfig's ``column``), never from an untrusted network caller.
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
    """Maps one of DuckDB's native type strings (as returned by
    ``DESCRIBE``, e.g. ``"BIGINT"``, ``"DECIMAL(18,3)"``,
    ``"TIMESTAMP WITH TIME ZONE"``) to Sentinel's canonical vocabulary
    (``DataSource.columns()``). ``DECIMAL``/``TIMESTAMP`` are matched by
    prefix since DuckDB parameterizes both (``DECIMAL(p,s)``,
    ``TIMESTAMP WITH TIME ZONE``) — everything else is an exact,
    case-insensitive match. A type this doesn't recognize maps to
    ``"unknown"`` rather than raising: an adapter's job is to report what
    it saw, not to judge whether it's expected — that's
    ``SchemaValidationRule``'s job, one layer up.
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
    """Applies the DataSource.max_value timezone contract (Milestone 3
    Part 3b): a ``datetime`` with no tzinfo is assumed UTC and stamped as
    such; one with tzinfo is converted to UTC; anything else (a number, a
    string, ``None``) passes through unchanged — the contract only
    concerns timestamp values."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value


@register_data_source
class DuckDBSource:
    """Reads a single local CSV file through DuckDB's SQL engine.

    ``config_reference`` is the path to that CSV file — the field
    Milestone 0's Dataset model reserved for exactly this kind of
    adapter-specific pointer. A missing or unreadable file surfaces as
    whatever error DuckDB itself raises when the first query runs — there
    is no Sentinel-specific wrapper adding value over that.
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
