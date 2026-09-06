from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.persistence.engine import get_connection


def test_get_connection_creates_a_db_file_at_the_given_path(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    assert not db_path.exists()

    get_connection(db_path)

    assert db_path.exists()


def test_get_connection_accepts_a_string_path_too(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    get_connection(str(db_path))
    assert db_path.exists()


def test_get_connection_reads_the_env_var_when_no_path_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "from_env.duckdb"
    monkeypatch.setenv("SENTINEL_DB_PATH", str(db_path))

    get_connection()

    assert db_path.exists()


def test_get_connection_defaults_to_sentinel_duckdb_in_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SENTINEL_DB_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    get_connection()

    assert (tmp_path / "sentinel.duckdb").exists()
