from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sentinel.datasources.sql_base import SqlDataSource


class _Recording(SqlDataSource):
    source_type: ClassVar[str] = "recording"

    def __init__(self, value: Any = 0, quote_char: str = '"') -> None:
        self.queries: list[str] = []
        self._value = value
        self._quote_char = quote_char

    def _table(self) -> str:
        return self._quote("orders")

    def _scalar(self, query: str) -> Any:
        self.queries.append(query)
        return self._value

    def columns(self) -> dict[str, str]:
        return {}


def test_capabilities_use_standard_aggregate_sql() -> None:
    source = _Recording(value=3)

    assert source.row_count() == 3
    assert source.null_count("name") == 3
    assert source.distinct_count("name") == 3
    source.max_value("name")

    assert source.queries == [
        'SELECT COUNT(*) FROM "orders"',
        'SELECT COUNT(*) FROM "orders" WHERE "name" IS NULL',
        'SELECT COUNT(DISTINCT "name") FROM "orders"',
        'SELECT MAX("name") FROM "orders"',
    ]


def test_identifiers_are_quoted_and_escaped() -> None:
    source = _Recording()
    source.null_count('evil" OR 1=1 --')
    assert source.queries[-1].endswith('WHERE "evil"" OR 1=1 --" IS NULL')


def test_backtick_engines_escape_backticks() -> None:
    source = _Recording(quote_char="`")
    source.distinct_count("a`b")
    assert source.queries[-1] == "SELECT COUNT(DISTINCT `a``b`) FROM `orders`"


def test_max_value_returns_utc_aware_datetimes() -> None:
    source = _Recording(value=datetime(2026, 1, 1, 9, 0))
    assert source.max_value("created_at") == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def test_max_value_is_none_for_no_values() -> None:
    assert _Recording(value=None).max_value("x") is None
