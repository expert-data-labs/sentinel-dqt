"""SnowflakeDataSource with a fake connector (live tests run only with credentials)."""

from __future__ import annotations

from typing import Any

import pytest

from sentinel.datasources import snowflake_source
from sentinel.datasources._common import ConfigReferenceError
from sentinel.datasources.snowflake_source import (
    SnowflakeDataSource,
    _canonical_type,
    _connection_args,
    _display,
    _resolve,
)
from tests.unit.datasources.fakes import FakeConnection, fake_driver, scalar

_URL = "snowflake://etl:pw@xy12345.eu-west-1/analytics/sales?warehouse=WH&role=QA&table=orders"


def _source(monkeypatch: pytest.MonkeyPatch, conn: FakeConnection) -> SnowflakeDataSource:
    monkeypatch.setattr(snowflake_source, "import_driver", lambda module, extra: fake_driver(conn))
    return SnowflakeDataSource(_URL)


def test_connection_args_come_from_the_url() -> None:
    args, table = _connection_args(_URL)
    assert table == "orders"
    assert args == {
        "account": "xy12345.eu-west-1",
        "user": "etl",
        "password": "pw",
        "database": "analytics",
        "schema": "sales",
        "warehouse": "WH",
        "role": "QA",
    }


def test_password_is_optional_for_other_authenticators() -> None:
    args, _ = _connection_args("snowflake://etl@acct/db/sch?authenticator=externalbrowser&table=t")
    assert "password" not in args
    assert args["authenticator"] == "externalbrowser"


@pytest.mark.parametrize(
    "bad",
    ["snowflake://acct/db?table=t", "snowflake://acct/db/sch/x?table=t", "pg://a/b/c?table=t"],
)
def test_bad_urls_are_rejected(bad: str) -> None:
    with pytest.raises(ConfigReferenceError):
        _connection_args(bad)


def test_plain_lower_case_names_resolve_to_upper_case() -> None:
    assert _resolve("order_id") == "ORDER_ID"
    assert _resolve("ORDER_ID") == "ORDER_ID"
    assert _resolve("OrderId") == "OrderId"  # mixed case is used exactly
    assert _resolve("order id") == "order id"


def test_upper_case_names_are_displayed_in_lower_case() -> None:
    assert _display("ORDER_ID") == "order_id"
    assert _display("OrderId") == "OrderId"


@pytest.mark.parametrize(
    ("data_type", "scale", "expected"),
    [
        ("NUMBER", 0, "integer"),
        ("NUMBER", 2, "decimal"),
        ("FLOAT", None, "float"),
        ("TEXT", None, "string"),
        ("BOOLEAN", None, "boolean"),
        ("TIMESTAMP_NTZ", None, "timestamp"),
        ("TIMESTAMP_TZ", None, "timestamp"),
        ("DATE", None, "date"),
        ("VARIANT", None, "unknown"),
    ],
)
def test_canonical_type(data_type: str, scale: int | None, expected: str) -> None:
    assert _canonical_type(data_type, scale) == expected


def test_queries_use_fully_qualified_resolved_names(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(scalar(0))
    _source(monkeypatch, conn).null_count("customer_id")
    assert conn.queries[0][0] == (
        'SELECT COUNT(*) FROM "ANALYTICS"."SALES"."ORDERS" WHERE "CUSTOMER_ID" IS NULL'
    )


def test_columns_reports_lower_case_names_and_types(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(query: str, params: Any) -> list[tuple[Any, ...]]:
        return [("ORDER_ID", "NUMBER", 0), ("Note", "TEXT", None)]

    conn = FakeConnection(respond)
    assert _source(monkeypatch, conn).columns() == {"order_id": "integer", "Note": "string"}
    assert conn.queries[0][1] == ("SALES", "ORDERS")
    assert '"ANALYTICS".information_schema.columns' in conn.queries[0][0]
