"""PostgresDataSource: reads one table in a Postgres database.

``config_reference`` is a connection URL with the table as a query
parameter, e.g. ``postgresql://user:pw@host:5432/db?table=orders``.
Identifiers are interpolated into SQL for the same reason as DuckDBSource.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import psycopg

from sentinel.datasources.registry import register_data_source

_POSTGRES_INTEGER_TYPES = {"smallint", "integer", "bigint"}
_POSTGRES_FLOAT_TYPES = {"double precision", "real"}
_POSTGRES_STRING_TYPES = {
    "character varying",
    "character",
    "varchar",
    "char",
    "text",
    "citext",
    "uuid",
}


def _canonical_type(postgres_type: str) -> str:
    """Map an ``information_schema`` data_type to a canonical type.

    Timestamps match by prefix (with or without time zone). Unrecognized types
    map to "unknown".
    """
    normalized = postgres_type.lower()
    if normalized.startswith("timestamp"):
        return "timestamp"
    if normalized in _POSTGRES_STRING_TYPES:
        return "string"
    if normalized in _POSTGRES_INTEGER_TYPES:
        return "integer"
    if normalized in _POSTGRES_FLOAT_TYPES:
        return "float"
    if normalized == "numeric":
        return "decimal"
    if normalized == "boolean":
        return "boolean"
    if normalized == "date":
        return "date"
    return "unknown"


def _as_utc(value: Any) -> Any:
    """Return datetimes as UTC (naive ones are assumed UTC); pass other values
    through.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value


def _parse_config_reference(config_reference: str) -> tuple[str, str]:
    """Split ``config_reference`` into (connection URL, table name).

    ``table`` is removed from the URL because libpq rejects it. Raises
    ValueError if it's missing.
    """
    parts = urlsplit(config_reference)
    query = parse_qs(parts.query, keep_blank_values=True)
    tables = query.pop("table", None)
    if not tables or not tables[0]:
        raise ValueError(
            "PostgresDataSource requires a config_reference URL with a "
            "'table' query parameter, e.g. "
            "'postgresql://user:password@host:5432/dbname?table=orders'"
        )
    table = tables[0]
    remaining_query = urlencode(query, doseq=True)
    connection_url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, remaining_query, parts.fragment)
    )
    return connection_url, table


@register_data_source
class PostgresDataSource:
    """Reads one Postgres table.

    Connection and missing-table errors surface as psycopg's own errors.
    """

    source_type: ClassVar[str] = "postgres"

    def __init__(self, config_reference: str | None) -> None:
        if config_reference is None:
            raise ValueError(
                "PostgresDataSource requires a Dataset with config_reference set "
                "to a connection URL, e.g. "
                "'postgresql://user:password@host:5432/dbname?table=orders'"
            )
        connection_url, table = _parse_config_reference(config_reference)
        self._table = table
        # Read-only single SELECTs: no need to hold a transaction open.
        self._conn = psycopg.connect(connection_url, autocommit=True)

    def _scalar(self, query: str) -> Any:
        with self._conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
        assert row is not None  # an aggregate query always returns exactly one row
        return row[0]

    def _quoted_table(self) -> str:
        return f'"{self._table}"'

    def row_count(self) -> int:
        return int(self._scalar(f"SELECT count(*) FROM {self._quoted_table()}"))

    def null_count(self, column: str) -> int:
        return int(
            self._scalar(f'SELECT count(*) FROM {self._quoted_table()} WHERE "{column}" IS NULL')
        )

    def distinct_count(self, column: str) -> int:
        return int(
            self._scalar(f'SELECT count(DISTINCT "{column}") FROM {self._quoted_table()}')
        )

    def max_value(self, column: str) -> Any:
        return _as_utc(self._scalar(f'SELECT max("{column}") FROM {self._quoted_table()}'))

    def columns(self) -> dict[str, str]:
        query = (
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = '{self._table}' ORDER BY ordinal_position"
        )
        with self._conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return {row[0]: _canonical_type(row[1]) for row in rows}
