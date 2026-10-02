"""Composition root: sets up what every CLI command needs."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from sentinel.persistence.engine import get_connection
from sentinel.persistence.schema import ensure_schema
from sentinel.registration import register_all


@dataclass(frozen=True)
class AppContext:
    """Shared CLI state: a store connection with its schema in place."""

    conn: duckdb.DuckDBPyConnection


def build_context() -> AppContext:
    """Register all implementations, open the store and create its schema.

    Idempotent; each command calls it once.
    """
    register_all()
    conn = get_connection()
    ensure_schema(conn)
    return AppContext(conn=conn)
