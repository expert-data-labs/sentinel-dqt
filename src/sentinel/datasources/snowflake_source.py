"""SnowflakeDataSource: reads one Snowflake table or view.

``config_reference``::

    snowflake://user:${SNOWFLAKE_PASSWORD}@account/database/schema?warehouse=WH&table=orders

``account`` is the account identifier (e.g. ``xy12345.eu-west-1`` or
``myorg-myaccount``). Other query parameters (``role``, ``authenticator``,
``private_key_file``, ...) are passed to ``snowflake.connector.connect``.
Requires the ``snowflake`` extra.

Names follow Snowflake's rules: plain names like ``orders`` or ``order_id``
mean the upper-case object (``ORDERS``), as if unquoted; anything else (mixed
case, spaces) is used exactly. ``columns()`` reports upper-case names in lower
case, so ``expected_schema`` can be written in lower case.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import unquote, urlsplit

from sentinel.datasources._common import (
    ConfigReferenceError,
    import_driver,
    pop_url_param,
    url_params,
)
from sentinel.datasources.registry import register_data_source
from sentinel.datasources.sql_base import SqlDataSource

_EXAMPLE = (
    "snowflake://user:${SNOWFLAKE_PASSWORD}@account/database/schema?warehouse=WH&table=orders"
)
_PLAIN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _resolve(name: str) -> str:
    """The stored object name: plain names are upper-cased, like unquoted SQL."""
    return name.upper() if _PLAIN_NAME.match(name) and name == name.lower() else name


def _display(name: str) -> str:
    """Upper-case stored names are shown in lower case; others unchanged."""
    return name.lower() if _PLAIN_NAME.match(name) and name == name.upper() else name


def _canonical_type(data_type: str, numeric_scale: int | None) -> str:
    """Map a Snowflake data_type to a canonical type. NUMBER with scale 0 is integer."""
    data_type = data_type.upper()
    if data_type in {"NUMBER", "DECIMAL", "NUMERIC"}:
        return "integer" if not numeric_scale else "decimal"
    if data_type in {"FLOAT", "DOUBLE", "REAL"}:
        return "float"
    if data_type in {"TEXT", "VARCHAR", "STRING", "CHAR"}:
        return "string"
    if data_type == "BOOLEAN":
        return "boolean"
    if data_type.startswith("TIMESTAMP"):
        return "timestamp"
    if data_type == "DATE":
        return "date"
    return "unknown"


def _connection_args(config_reference: str) -> tuple[dict[str, Any], str]:
    """``snowflake.connector.connect`` arguments and the table name."""
    url, table = pop_url_param(config_reference, "table", example=_EXAMPLE)
    parts = urlsplit(url)
    path = [unquote(p) for p in parts.path.split("/") if p]
    if parts.scheme != "snowflake" or not parts.hostname or len(path) != 2:
        raise ConfigReferenceError(f"Expected a Snowflake URL like {_EXAMPLE!r}")
    args: dict[str, Any] = {
        "account": parts.hostname,
        "user": unquote(parts.username or ""),
        "database": path[0],
        "schema": path[1],
        **url_params(url),
    }
    if parts.password:
        args["password"] = unquote(parts.password)
    return args, table


@register_data_source
class SnowflakeDataSource(SqlDataSource):
    """Reads one Snowflake table or view."""

    source_type: ClassVar[str] = "snowflake"

    def __init__(self, config_reference: str | None) -> None:
        if config_reference is None:
            raise ValueError(f"SnowflakeDataSource requires a config_reference, e.g. {_EXAMPLE!r}")
        args, table = _connection_args(config_reference)
        self._database, self._schema, self._name = args["database"], args["schema"], table
        connector = import_driver("snowflake.connector", "snowflake")
        self._conn = connector.connect(**args)

    def _quote(self, identifier: str) -> str:
        return super()._quote(_resolve(identifier))

    def _table(self) -> str:
        return ".".join(self._quote(p) for p in (self._database, self._schema, self._name))

    def _scalar(self, query: str) -> Any:
        cur = self._conn.cursor()
        try:
            cur.execute(query)
            row = cur.fetchone()
        finally:
            cur.close()
        assert row is not None  # aggregates always return one row
        return row[0]

    def columns(self) -> dict[str, str]:
        cur = self._conn.cursor()
        try:
            cur.execute(
                f"SELECT column_name, data_type, numeric_scale "
                f"FROM {self._quote(self._database)}.information_schema.columns "
                f"WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (_resolve(self._schema), _resolve(self._name)),
            )
            rows = cur.fetchall()
        finally:
            cur.close()
        return {_display(row[0]): _canonical_type(row[1], row[2]) for row in rows}
