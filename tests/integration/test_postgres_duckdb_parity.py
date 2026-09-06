"""Milestone 3's Adapter Compatibility test: the exact same Rule
executions, run once against a real DuckDBSource (a temp CSV file) and
once against a real PostgresDataSource (a temp table), given the same
logical dataset -- proving Rules are backend-independent (FR-10), not
just structurally (same Protocol) but in practice against two real
engines.

Skips entirely if Postgres isn't reachable (SENTINEL_TEST_POSTGRES_DSN,
defaulting to the docker-compose/CI credentials in docker-compose.yml and
.github/workflows/ci.yml) -- a contributor running `pytest` without first
starting Postgres locally still gets a passing suite, with this one file
skipped rather than failing; CI always has Postgres up via its `services:`
block, so it always runs there. DuckDB has no equivalent skip: it's an
embedded engine reading a plain temp file, always available wherever
duckdb itself is installed (already a hard dependency since Milestone 2).

Row count, null rate, uniqueness, and freshness are asserted to produce
matching values from both adapters, given matching data -- these rules
measure the data, and the data is the same on both sides. Schema
validation is deliberately tested differently: rather than asserting a
specific canonical type for, say, order_total (DuckDB's CSV type sniffing
isn't empirically verified in the environment these tests were authored
in -- see docs/architecture/0004-milestone-3-architecture.md,
"Verification gap"), each adapter's own real ``columns()`` output is used
to build its own expected_schema. That proves SchemaValidationRule's
match/mismatch logic is correct against a real adapter's real schema,
without this test file needing to predict which specific type either
engine infers.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from sentinel.datasources.base import DataSource
from sentinel.datasources.duckdb_source import DuckDBSource
from sentinel.datasources.postgres_source import PostgresDataSource
from sentinel.domain import RuleConfig
from sentinel.rules.freshness import FreshnessRule
from sentinel.rules.null_rate import NullRateRule
from sentinel.rules.row_count import RowCountRule
from sentinel.rules.schema_validation import SchemaValidationRule
from sentinel.rules.uniqueness import UniquenessRule

_POSTGRES_DSN = os.environ.get(
    "SENTINEL_TEST_POSTGRES_DSN",
    "postgresql://sentinel:sentinel@localhost:5432/sentinel",
)
_TABLE_NAME = "sentinel_parity_test_orders"

_NOW = datetime.now(UTC)
_ROWS: list[dict[str, Any]] = [
    {
        "order_id": 1,
        "customer_id": "C1",
        "order_total": 10.5,
        "updated_at": _NOW - timedelta(minutes=5),
    },
    {
        "order_id": 2,
        "customer_id": "C2",
        "order_total": 20.0,
        "updated_at": _NOW - timedelta(minutes=15),
    },
    {
        "order_id": 3,
        "customer_id": None,
        "order_total": 30.25,
        "updated_at": _NOW - timedelta(minutes=1),
    },
]


def _connect_or_skip() -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(_POSTGRES_DSN, connect_timeout=2, autocommit=True)
    except Exception as exc:  # pragma: no cover - exercised only when Postgres is down
        pytest.skip(
            f"Postgres not reachable at {_POSTGRES_DSN!r} ({exc}); "
            "start it with `docker compose up -d` to run this file"
        )


@pytest.fixture
def postgres_source() -> Iterator[DataSource]:
    conn = _connect_or_skip()
    with conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{_TABLE_NAME}"')
        cur.execute(
            f'CREATE TABLE "{_TABLE_NAME}" ('
            "order_id integer, customer_id varchar, order_total double precision, "
            "updated_at timestamptz)"
        )
        for row in _ROWS:
            cur.execute(
                f'INSERT INTO "{_TABLE_NAME}" '
                "(order_id, customer_id, order_total, updated_at) VALUES (%s, %s, %s, %s)",
                (row["order_id"], row["customer_id"], row["order_total"], row["updated_at"]),
            )
    conn.close()

    source: DataSource = PostgresDataSource(f"{_POSTGRES_DSN}?table={_TABLE_NAME}")
    try:
        yield source
    finally:
        cleanup_conn = _connect_or_skip()
        with cleanup_conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "{_TABLE_NAME}"')
        cleanup_conn.close()


@pytest.fixture
def duckdb_source(tmp_path: Path) -> DataSource:
    csv_path = tmp_path / "orders.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["order_id", "customer_id", "order_total", "updated_at"]
        )
        writer.writeheader()
        for row in _ROWS:
            writer.writerow(
                {
                    "order_id": row["order_id"],
                    "customer_id": row["customer_id"] if row["customer_id"] is not None else "",
                    "order_total": row["order_total"],
                    "updated_at": row["updated_at"].isoformat(),
                }
            )
    return DuckDBSource(str(csv_path))


def _rule_config(name: str, rule_type: str, **extra: object) -> RuleConfig:
    return RuleConfig.model_validate(
        {"name": name, "type": rule_type, "threshold": {"strategy": "static", "max": 0}, **extra}
    )


def test_row_count_matches_between_duckdb_and_postgres(
    duckdb_source: DataSource, postgres_source: DataSource
) -> None:
    config = _rule_config("row_count", "row_count")
    duckdb_metric = RowCountRule().compute(duckdb_source, config)
    postgres_metric = RowCountRule().compute(postgres_source, config)
    assert duckdb_metric.value == postgres_metric.value == 3.0


def test_null_rate_matches_between_duckdb_and_postgres(
    duckdb_source: DataSource, postgres_source: DataSource
) -> None:
    config = _rule_config("customer_id_not_null", "null_rate", column="customer_id")
    duckdb_metric = NullRateRule().compute(duckdb_source, config)
    postgres_metric = NullRateRule().compute(postgres_source, config)
    assert duckdb_metric.value == pytest.approx(1 / 3)
    assert postgres_metric.value == pytest.approx(1 / 3)


def test_uniqueness_matches_between_duckdb_and_postgres(
    duckdb_source: DataSource, postgres_source: DataSource
) -> None:
    config = _rule_config("unique_order_id", "uniqueness", column="order_id")
    duckdb_metric = UniquenessRule().compute(duckdb_source, config)
    postgres_metric = UniquenessRule().compute(postgres_source, config)
    assert duckdb_metric.value == postgres_metric.value == 0.0


def test_freshness_matches_between_duckdb_and_postgres(
    duckdb_source: DataSource, postgres_source: DataSource
) -> None:
    config = _rule_config("orders_freshness", "freshness", column="updated_at")
    duckdb_metric = FreshnessRule().compute(duckdb_source, config)
    postgres_metric = FreshnessRule().compute(postgres_source, config)
    # Both sides' most recent updated_at is ~1 minute before _NOW; small
    # wall-clock slack since the two compute() calls aren't simultaneous.
    assert duckdb_metric.value == pytest.approx(1.0, abs=0.5)
    assert postgres_metric.value == pytest.approx(1.0, abs=0.5)


def test_schema_validation_reports_zero_differences_against_each_adapters_own_schema(
    duckdb_source: DataSource, postgres_source: DataSource
) -> None:
    for source in (duckdb_source, postgres_source):
        expected_schema = source.columns()
        config = _rule_config("orders_schema", "schema", expected_schema=expected_schema)
        metric = SchemaValidationRule().compute(source, config)
        assert metric.value == 0.0, metric.details


def test_schema_validation_detects_a_real_type_mismatch_on_each_adapter(
    duckdb_source: DataSource, postgres_source: DataSource
) -> None:
    for source in (duckdb_source, postgres_source):
        expected_schema = dict(source.columns())
        # order_id is always numeric on both adapters; "string" is always wrong.
        expected_schema["order_id"] = "string"
        config = _rule_config("orders_schema", "schema", expected_schema=expected_schema)
        metric = SchemaValidationRule().compute(source, config)
        assert metric.value == 1.0, metric.details


def test_schema_validation_detects_a_real_missing_column_on_each_adapter(
    duckdb_source: DataSource, postgres_source: DataSource
) -> None:
    for source in (duckdb_source, postgres_source):
        expected_schema = dict(source.columns())
        expected_schema["a_column_that_does_not_exist"] = "string"
        config = _rule_config("orders_schema", "schema", expected_schema=expected_schema)
        metric = SchemaValidationRule().compute(source, config)
        assert metric.value == 1.0, metric.details
