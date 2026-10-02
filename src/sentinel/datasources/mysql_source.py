"""MySQLDataSource: reads one table in MySQL or MariaDB.

``config_reference``: ``mysql://user:${MYSQL_PASSWORD}@host:3306/database?table=orders``.
Requires the ``mysql`` extra (PyMySQL). DATETIME values are assumed to be UTC.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import unquote, urlsplit

from sentinel.datasources._common import ConfigReferenceError, import_driver, pop_url_param
from sentinel.datasources.registry import register_data_source
from sentinel.datasources.sql_base import SqlDataSource

_EXAMPLE = "mysql://user:password@host:3306/database?table=orders"
_INTEGER_TYPES = {"tinyint", "smallint", "mediumint", "int", "integer", "bigint", "year"}
_FLOAT_TYPES = {"float", "double", "real"}
_STRING_TYPES = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext", "enum", "set"}


def _canonical_type(data_type: str, column_type: str) -> str:
    """Map MySQL ``information_schema`` types to a canonical type.

    ``tinyint(1)`` is MySQL's BOOLEAN, so it maps to boolean.
    """
    data_type, column_type = data_type.lower(), column_type.lower()
    if column_type.startswith("tinyint(1)"):
        return "boolean"
    if data_type in _INTEGER_TYPES:
        return "integer"
    if data_type in _FLOAT_TYPES:
        return "float"
    if data_type == "decimal":
        return "decimal"
    if data_type in _STRING_TYPES:
        return "string"
    if data_type in {"datetime", "timestamp"}:
        return "timestamp"
    if data_type == "date":
        return "date"
    return "unknown"


def _connection_args(config_reference: str) -> tuple[dict[str, Any], str]:
    """PyMySQL connect() arguments and the table name from ``config_reference``."""
    url, table = pop_url_param(config_reference, "table", example=_EXAMPLE)
    parts = urlsplit(url)
    if parts.scheme not in {"mysql", "mariadb"}:
        raise ConfigReferenceError(f"Expected a mysql:// URL, e.g. {_EXAMPLE!r}")
    database = parts.path.lstrip("/")
    if not database:
        raise ConfigReferenceError(f"The MySQL URL needs a database name, e.g. {_EXAMPLE!r}")
    args: dict[str, Any] = {
        "host": parts.hostname or "localhost",
        "port": parts.port or 3306,
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": database,
        "autocommit": True,
    }
    return args, table


@register_data_source
class MySQLDataSource(SqlDataSource):
    """Reads one MySQL/MariaDB table."""

    source_type: ClassVar[str] = "mysql"
    _quote_char = "`"

    def __init__(self, config_reference: str | None) -> None:
        if config_reference is None:
            raise ValueError(f"MySQLDataSource requires a config_reference, e.g. {_EXAMPLE!r}")
        args, self._name = _connection_args(config_reference)
        pymysql = import_driver("pymysql", "mysql")
        self._conn = pymysql.connect(**args)

    def _table(self) -> str:
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
                "SELECT column_name, data_type, column_type FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = %s ORDER BY ordinal_position",
                (self._name,),
            )
            rows = cur.fetchall()
        return {row[0]: _canonical_type(row[1], row[2]) for row in rows}
