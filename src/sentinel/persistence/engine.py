"""Opens a connection to Sentinel's DuckDB store."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

_ENV_VAR = "SENTINEL_DB_PATH"
_DEFAULT_PATH = "sentinel.duckdb"


def get_connection(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open (or create) the store.

    Path resolution: ``path`` argument, then ``SENTINEL_DB_PATH``, then
    ``./sentinel.duckdb``. The parent directory must already exist.
    """
    resolved = path if path is not None else os.environ.get(_ENV_VAR, _DEFAULT_PATH)
    return duckdb.connect(str(resolved))
