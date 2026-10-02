"""Fake database drivers for adapter unit tests: record SQL, return canned rows."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

Responder = Callable[[str, Any], list[tuple[Any, ...]]]


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self._conn.queries.append((query, params))
        self._rows = self._conn.respond(query, params)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def close(self) -> None:
        pass

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


class FakeConnection:
    """A DB-API-style connection. ``respond(query, params)`` returns result rows."""

    def __init__(self, respond: Responder) -> None:
        self.respond = respond
        self.queries: list[tuple[str, Any]] = []
        self.connect_kwargs: dict[str, Any] = {}

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def fake_driver(conn: FakeConnection) -> SimpleNamespace:
    """A module-like object whose ``connect(**kwargs)`` returns ``conn``."""

    def connect(**kwargs: Any) -> FakeConnection:
        conn.connect_kwargs = kwargs
        return conn

    return SimpleNamespace(connect=connect)


def scalar(value: Any) -> Responder:
    """Respond to every query with a single-value row."""
    return lambda query, params: [(value,)]
