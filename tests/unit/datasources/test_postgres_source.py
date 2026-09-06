"""Unit tests for PostgresDataSource's pure helper functions.

Deliberately scoped to what's verifiable without a live Postgres
connection: ``_canonical_type`` and ``_parse_config_reference`` are pure
functions, and the two constructor error paths below both raise before
``psycopg.connect`` is ever called. Adapter-method tests that need a real
table (``row_count``, ``null_count``, ``columns``, ...) belong to the
cross-adapter integration tests introduced once docker-compose brings up a
real Postgres for CI -- see docs/architecture/0004-milestone-3-architecture.md
Part 8/9. Running this file at all requires ``psycopg`` to be installed
(added to pyproject.toml this milestone) -- run ``uv sync`` first.
"""

from __future__ import annotations

import pytest

from sentinel.datasources.postgres_source import (
    PostgresDataSource,
    _canonical_type,
    _parse_config_reference,
)


@pytest.mark.parametrize(
    ("postgres_type", "expected"),
    [
        ("bigint", "integer"),
        ("integer", "integer"),
        ("smallint", "integer"),
        ("double precision", "float"),
        ("real", "float"),
        ("numeric", "decimal"),
        ("character varying", "string"),
        ("text", "string"),
        ("boolean", "boolean"),
        ("date", "date"),
        ("timestamp without time zone", "timestamp"),
        ("timestamp with time zone", "timestamp"),
        ("bytea", "unknown"),
    ],
)
def test_canonical_type_mapping(postgres_type: str, expected: str) -> None:
    assert _canonical_type(postgres_type) == expected


def test_canonical_type_is_case_insensitive() -> None:
    assert _canonical_type("BIGINT") == "integer"


def test_parse_config_reference_splits_url_and_table() -> None:
    connection_url, table = _parse_config_reference(
        "postgresql://user:password@localhost:5432/sentinel?table=orders"
    )
    assert table == "orders"
    assert "table=" not in connection_url
    assert connection_url.startswith("postgresql://user:password@localhost:5432/sentinel")


def test_parse_config_reference_preserves_other_query_parameters() -> None:
    connection_url, table = _parse_config_reference(
        "postgresql://user:password@localhost:5432/sentinel?table=orders&sslmode=require"
    )
    assert table == "orders"
    assert "sslmode=require" in connection_url
    assert "table=" not in connection_url


def test_parse_config_reference_requires_a_table_parameter() -> None:
    with pytest.raises(ValueError, match="table"):
        _parse_config_reference("postgresql://user:password@localhost:5432/sentinel")


def test_construction_requires_a_config_reference() -> None:
    with pytest.raises(ValueError, match="config_reference"):
        PostgresDataSource(None)


def test_construction_requires_a_table_query_parameter() -> None:
    with pytest.raises(ValueError, match="table"):
        PostgresDataSource("postgresql://user:password@localhost:5432/sentinel")
