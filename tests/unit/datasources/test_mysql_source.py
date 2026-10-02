"""MySQLDataSource with a fake PyMySQL driver (real MySQL: test_adapter_contract.py)."""

from __future__ import annotations

from typing import Any

import pytest

from sentinel.datasources import mysql_source
from sentinel.datasources._common import ConfigReferenceError
from sentinel.datasources.mysql_source import MySQLDataSource, _canonical_type, _connection_args
from tests.unit.datasources.fakes import FakeConnection, fake_driver, scalar

_URL = "mysql://app:p%40ss@db.internal:3307/shop?table=orders"


def _source(monkeypatch: pytest.MonkeyPatch, conn: FakeConnection) -> MySQLDataSource:
    monkeypatch.setattr(mysql_source, "import_driver", lambda module, extra: fake_driver(conn))
    return MySQLDataSource(_URL)


def test_connection_args_come_from_the_url() -> None:
    args, table = _connection_args(_URL)
    assert table == "orders"
    assert args == {
        "host": "db.internal",
        "port": 3307,
        "user": "app",
        "password": "p@ss",
        "database": "shop",
        "autocommit": True,
    }


@pytest.mark.parametrize(
    "bad", ["mysql://h/shop", "postgres://h/shop?table=t", "mysql://h?table=t"]
)
def test_bad_urls_are_rejected(bad: str) -> None:
    with pytest.raises(ConfigReferenceError):
        _connection_args(bad)


@pytest.mark.parametrize(
    ("data_type", "column_type", "expected"),
    [
        ("int", "int", "integer"),
        ("bigint", "bigint unsigned", "integer"),
        ("tinyint", "tinyint(1)", "boolean"),
        ("tinyint", "tinyint(4)", "integer"),
        ("decimal", "decimal(10,2)", "decimal"),
        ("double", "double", "float"),
        ("varchar", "varchar(255)", "string"),
        ("enum", "enum('a','b')", "string"),
        ("datetime", "datetime", "timestamp"),
        ("date", "date", "date"),
        ("json", "json", "unknown"),
    ],
)
def test_canonical_type(data_type: str, column_type: str, expected: str) -> None:
    assert _canonical_type(data_type, column_type) == expected


def test_queries_use_backtick_quoting(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(scalar(5))
    source = _source(monkeypatch, conn)

    assert source.row_count() == 5
    source.null_count("customer_id")

    assert conn.queries[0][0] == "SELECT COUNT(*) FROM `orders`"
    assert conn.queries[1][0] == "SELECT COUNT(*) FROM `orders` WHERE `customer_id` IS NULL"
    assert conn.connect_kwargs["database"] == "shop"


def test_columns_reads_information_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(query: str, params: Any) -> list[tuple[Any, ...]]:
        return [("id", "bigint", "bigint"), ("active", "tinyint", "tinyint(1)")]

    conn = FakeConnection(respond)
    assert _source(monkeypatch, conn).columns() == {"id": "integer", "active": "boolean"}
    assert conn.queries[0][1] == ("orders",)
