"""SqlDataSource: shared implementation for SQL engines.

Every SQL adapter answers the same questions with the same aggregate SQL. A
subclass supplies only what differs between engines:

- ``_table()``: how to reference the dataset (a table name, ``read_parquet(...)``)
- ``_scalar(query)``: run a query and return its single value
- ``columns()``: column names and canonical types (engines describe schema differently)
- ``_quote_char``: the identifier quote character (``"`` or a backtick)

Identifiers come from local YAML. They are always quoted, with embedded quote
characters doubled, so a column name can't break out of the SQL text.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sentinel.datasources._common import as_utc


class SqlDataSource(ABC):
    """Base class for SQL adapters. Subclasses also set ``source_type`` and register."""

    _quote_char = '"'

    def _quote(self, identifier: str) -> str:
        q = self._quote_char
        return q + identifier.replace(q, q + q) + q

    @abstractmethod
    def _table(self) -> str:
        """SQL that references the dataset in a FROM clause."""

    @abstractmethod
    def _scalar(self, query: str) -> Any:
        """Run ``query`` and return the first column of its single row."""

    @abstractmethod
    def columns(self) -> dict[str, str]: ...

    def row_count(self) -> int:
        return int(self._scalar(f"SELECT COUNT(*) FROM {self._table()}"))

    def null_count(self, column: str) -> int:
        return int(
            self._scalar(
                f"SELECT COUNT(*) FROM {self._table()} WHERE {self._quote(column)} IS NULL"
            )
        )

    def distinct_count(self, column: str) -> int:
        return int(
            self._scalar(f"SELECT COUNT(DISTINCT {self._quote(column)}) FROM {self._table()}")
        )

    def max_value(self, column: str) -> Any:
        return as_utc(self._scalar(f"SELECT MAX({self._quote(column)}) FROM {self._table()}"))
