"""BigQueryDataSource with a fake client (live tests run only with credentials)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sentinel.datasources import bigquery_source
from sentinel.datasources._common import ConfigReferenceError
from sentinel.datasources.bigquery_source import (
    BigQueryDataSource,
    _canonical_type,
    _parse_config_reference,
)


class _FakeClient:
    def __init__(self, project: str, location: str | None) -> None:
        self.project, self.location = project, location
        self.queries: list[str] = []

    def query(self, sql: str) -> Any:
        self.queries.append(sql)
        return SimpleNamespace(result=lambda: [(7,)])

    def get_table(self, ref: str) -> Any:
        self.table_ref = ref
        return SimpleNamespace(
            schema=[
                SimpleNamespace(name="id", field_type="INT64", mode="REQUIRED"),
                SimpleNamespace(name="tags", field_type="STRING", mode="REPEATED"),
                SimpleNamespace(name="at", field_type="TIMESTAMP", mode="NULLABLE"),
            ]
        )


def _source(monkeypatch: pytest.MonkeyPatch) -> tuple[BigQueryDataSource, list[_FakeClient]]:
    clients: list[_FakeClient] = []

    def client(project: str, location: str | None) -> _FakeClient:
        clients.append(_FakeClient(project, location))
        return clients[-1]

    driver = SimpleNamespace(Client=client)
    monkeypatch.setattr(bigquery_source, "import_driver", lambda module, extra: driver)
    return BigQueryDataSource("bigquery://my-proj/sales?table=orders&location=EU"), clients


def test_parse_config_reference() -> None:
    assert _parse_config_reference("bigquery://my-proj/sales?table=orders") == (
        "my-proj",
        "sales",
        "orders",
        None,
    )


@pytest.mark.parametrize(
    "bad", ["bigquery://proj?table=t", "bigquery://proj/a/b?table=t", "bigquery://proj/ds"]
)
def test_bad_urls_are_rejected(bad: str) -> None:
    with pytest.raises(ConfigReferenceError):
        _parse_config_reference(bad)


@pytest.mark.parametrize(
    ("field_type", "mode", "expected"),
    [
        ("INT64", "NULLABLE", "integer"),
        ("FLOAT64", "NULLABLE", "float"),
        ("NUMERIC", "NULLABLE", "decimal"),
        ("BOOL", "NULLABLE", "boolean"),
        ("DATETIME", "NULLABLE", "timestamp"),
        ("DATE", "NULLABLE", "date"),
        ("STRING", "REPEATED", "unknown"),
        ("RECORD", "NULLABLE", "unknown"),
    ],
)
def test_canonical_type(field_type: str, mode: str, expected: str) -> None:
    assert _canonical_type(field_type, mode) == expected


def test_queries_use_backtick_qualified_names(monkeypatch: pytest.MonkeyPatch) -> None:
    source, clients = _source(monkeypatch)

    assert source.distinct_count("customer_id") == 7

    assert clients[0].project == "my-proj" and clients[0].location == "EU"
    assert clients[0].queries == [
        "SELECT COUNT(DISTINCT `customer_id`) FROM `my-proj`.`sales`.`orders`"
    ]


def test_columns_come_from_the_table_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    source, clients = _source(monkeypatch)
    assert source.columns() == {"id": "integer", "tags": "unknown", "at": "timestamp"}
    assert clients[0].table_ref == "my-proj.sales.orders"
