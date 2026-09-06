"""PostgresDataSource: a DataSource adapter that queries a table in a
Postgres database.

Milestone 3's second adapter (docs/architecture/0004-milestone-3-architecture.md
Part 3c), added specifically to prove FreshnessRule and SchemaValidationRule
are backend-independent -- the same rule-level test cases run against both
this and DuckDBSource (tests/unit/datasources/test_*_source.py's shared
cases, wired up once docker-compose brings up a real Postgres for CI).

``config_reference`` carries both a connection target and a table name as
one string, since Dataset/Policy's schema wasn't changed for this
milestone: a Postgres connection URL with the table name as a query
parameter, e.g.
``postgresql://user:password@host:5432/dbname?table=orders``. See
_parse_config_reference below and the architecture doc for why a query
parameter was chosen over, say, a second Dataset field.

SQL here is built with plain string interpolation, not parameter binding
-- the same choice DuckDBSource makes and for the same reason: psycopg's
placeholders bind *values*, not identifiers or table names, and both the
table name and column names come from this process's own trusted local
config (a Dataset's ``config_reference``, a RuleConfig's ``column``),
never from an untrusted network caller.
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
    """Maps one of Postgres's ``information_schema.columns.data_type``
    strings (e.g. ``"bigint"``, ``"numeric"``, ``"timestamp with time
    zone"``) to Sentinel's canonical vocabulary (``DataSource.columns()``).
    ``timestamp`` is matched by prefix, since Postgres reports both
    ``"timestamp with time zone"`` and ``"timestamp without time zone"``
    that way -- everything else is an exact, case-insensitive match. A
    type this doesn't recognize maps to ``"unknown"`` rather than raising,
    mirroring DuckDBSource's ``_canonical_type``: an adapter's job is to
    report what it saw, not to judge whether it's expected -- that's
    SchemaValidationRule's job, one layer up.
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
    """Applies the DataSource.max_value timezone contract (Milestone 3
    Part 3b) -- identical in substance to DuckDBSource's ``_as_utc``: a
    ``datetime`` with no tzinfo is assumed UTC and stamped as such (the
    case for a Postgres ``timestamp without time zone`` column); one with
    tzinfo is converted to UTC (``timestamp with time zone``); anything
    else passes through unchanged."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value


def _parse_config_reference(config_reference: str) -> tuple[str, str]:
    """Splits a PostgresDataSource ``config_reference`` into a plain
    Postgres connection URL (the ``table`` query parameter stripped out --
    it isn't a libpq connection parameter, and passing it through would
    make ``psycopg.connect`` fail) and the table name that parameter
    named.

    Raises ValueError if ``table`` is missing, at construction time rather
    than as a confusing failure the first time a query runs.
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
    """Reads a single table in a Postgres database.

    ``config_reference`` is the connection-URL-plus-table-parameter string
    described in the module docstring. A missing/unreachable database or
    nonexistent table surfaces as whatever error psycopg itself raises --
    the same "no Sentinel-specific wrapper" choice DuckDBSource makes for
    a missing CSV file.
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
        # autocommit=True: every DataSource method is a single read-only
        # SELECT: no reason to hold an open transaction across calls.
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
