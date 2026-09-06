"""Connects to Sentinel's own persistence store.

Deliberately minimal: one function, no connection pooling, no ORM engine
configuration — DuckDB's Python API is a direct connection to a single
file. ``path`` is accepted explicitly (rather than only ever reading the
environment) so tests can point at a temp file without touching process
environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

_ENV_VAR = "SENTINEL_DB_PATH"
_DEFAULT_PATH = "sentinel.duckdb"


def get_connection(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open (creating if necessary) the persistence store.

    Resolution order: the explicit ``path`` argument; else the
    ``SENTINEL_DB_PATH`` environment variable; else ``./sentinel.duckdb``
    relative to the current working directory. The containing directory
    must already exist — DuckDB, like sqlite3, does not create parent
    directories on its own.
    """
    resolved = path if path is not None else os.environ.get(_ENV_VAR, _DEFAULT_PATH)
    return duckdb.connect(str(resolved))
