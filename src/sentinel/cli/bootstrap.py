"""Composition root for the CLI.

One function, called once per invocation, at the top of whichever command
runs: registers every concrete Rule/ThresholdStrategy/DataSource
implementation and opens the persistence store, then hands the result to
the command as a plain argument. No DI framework, no container — the
brief this milestone works from asks for exactly that restraint, and
there's only ever one thing to wire up per process lifetime.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from sentinel.persistence.engine import get_connection
from sentinel.persistence.schema import ensure_schema
from sentinel.registration import register_all


@dataclass(frozen=True)
class AppContext:
    """What a CLI command needs that isn't specific to its own arguments:
    a persistence connection whose schema is already guaranteed to exist.
    Rule/ThresholdStrategy/DataSource registration has no object of its
    own to hold — it lives in each registry's module-level dict — so
    there's nothing to carry for it beyond having called register_all()."""

    conn: duckdb.DuckDBPyConnection


def build_context() -> AppContext:
    """Register every concrete implementation, open the persistence
    store (SENTINEL_DB_PATH, default ./sentinel.duckdb), and make sure
    its schema exists. Safe to call more than once per process — both
    register_all() and ensure_schema() are themselves idempotent — but
    each CLI command calls it exactly once, at the top."""
    register_all()
    conn = get_connection()
    ensure_schema(conn)
    return AppContext(conn=conn)
