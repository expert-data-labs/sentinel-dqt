"""PostgresDataSource: reads one table in a Postgres database.

``config_reference`` is a connection URL with the table as a query parameter:
``postgresql://user:${PGPASSWORD}@host:5432/db?table=orders``. Use
``schema.table`` for a table outside the search path. Other query parameters
(``sslmode=require``) are passed to the connection.
"""

from __future__ import annotations

from typing import Any, ClassVar

import psycopg

from sentinel.datasources._common import as_utc, pop_url_param
from sentinel.datasources.registry import register_data_source
from sentinel.datasources.sql_base import SqlDataSource

_EXAMPLE = "postgresql://user:password@host:5432/dbname?table=orders"
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

# Kept for callers that imported it from here.
_as_utc = as_utc


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


def _parse_config_reference(config_reference: str) -> tuple[str, str]:
    """Split ``config_reference`` into (connection URL, table name).

    ``table`` is removed from the URL because libpq rejects it.
    """
    return pop_url_param(config_reference, "table", example=_EXAMPLE)


@register_data_source
class PostgresDataSource(SqlDataSource):
    """Reads one Postgres table. Connection errors surface as psycopg's own errors."""

    source_type: ClassVar[str] = "postgres"

    def __init__(self, config_reference: str | None) -> None:
        if config_reference is None:
            raise ValueError(
                f"PostgresDataSource requires a Dataset with config_reference set "
                f"to a connection URL, e.g. {_EXAMPLE!r}"
            )
        connection_url, table = _parse_config_reference(config_reference)
        schema, _, name = table.rpartition(".")
        self._schema = schema or None
        self._name = name
        # Read-only single SELECTs: no need to hold a transaction open.
        self._conn = psycopg.connect(connection_url, autocommit=True)

    def _table(self) -> str:
        if self._schema:
            return f"{self._quote(self._schema)}.{self._quote(self._name)}"
        return self._quote(self._name)

    def _scalar(self, query: str) -> Any:
        with self._conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
        assert row is not None  # aggregates always return one row
        return row[0]

    def columns(self) -> dict[str, str]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = %s AND table_schema = COALESCE(%s, current_schema()) "
                "ORDER BY ordinal_position",
                (self._name, self._schema),
            )
            rows = cur.fetchall()
        return {row[0]: _canonical_type(row[1]) for row in rows}
