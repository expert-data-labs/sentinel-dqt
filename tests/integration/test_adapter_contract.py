"""The DataSource contract, checked against every real backend that's reachable.

The same four rows are loaded into each backend, and every adapter must give
the same answers. That is what lets a rule written once run anywhere.

| Backend          | Needs                                                        |
|------------------|--------------------------------------------------------------|
| duckdb-csv/-parquet | nothing                                                   |
| postgres         | SENTINEL_TEST_POSTGRES_DSN (default: docker compose)          |
| mysql            | SENTINEL_TEST_MYSQL_URL (default: docker compose), mysql extra |
| mongodb          | SENTINEL_TEST_MONGODB_URL (default: docker compose), mongodb extra |
| snowflake        | SENTINEL_TEST_SNOWFLAKE_URL (snowflake://user:pw@acct/db/schema?warehouse=WH) |
| bigquery         | SENTINEL_TEST_BIGQUERY_URL (bigquery://project/dataset) + credentials |

Unreachable backends are skipped. Backends named in SENTINEL_REQUIRE_BACKENDS
(comma-separated, set in CI) fail instead of skipping.
"""

from __future__ import annotations

import csv
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest

from sentinel.datasources import DataSource
from sentinel.datasources._common import MissingDriverError, import_driver
from sentinel.datasources.bigquery_source import BigQueryDataSource
from sentinel.datasources.duckdb_source import DuckDBSource
from sentinel.datasources.mongodb_source import MongoDataSource
from sentinel.datasources.mysql_source import MySQLDataSource
from sentinel.datasources.postgres_source import PostgresDataSource
from sentinel.datasources.snowflake_source import SnowflakeDataSource

_NOW = datetime.now(UTC).replace(microsecond=0)

# (id, name, amount, created_at); None means null (missing, for MongoDB amount).
Row = tuple[int, str | None, float | None, datetime]
_ROWS: list[Row] = [
    (1, "a", 10.5, _NOW - timedelta(minutes=5)),
    (2, "a", 20.0, _NOW - timedelta(minutes=15)),
    (3, None, 30.25, _NOW - timedelta(minutes=1)),
    (4, "b", None, _NOW - timedelta(minutes=30)),
]
_EXPECTED_COLUMNS = {
    "id": "integer",
    "name": "string",
    "amount": "float",
    "created_at": "timestamp",
}

# A backend loads rows into a fresh table/file/collection and returns an adapter for it.
Loader = Callable[[list[Row]], DataSource]
Backend = Callable[[pytest.FixtureRequest, Path], Loader]


def _unavailable(name: str, reason: str) -> NoReturn:
    required = {b.strip() for b in os.environ.get("SENTINEL_REQUIRE_BACKENDS", "").split(",")}
    if name in required:
        pytest.fail(f"{name} is required but unavailable: {reason}")
    pytest.skip(f"{name} unavailable: {reason}")


def _driver(name: str, module: str, extra: str) -> Any:
    try:
        return import_driver(module, extra)
    except MissingDriverError as exc:
        _unavailable(name, str(exc))


def _unique_name() -> str:
    return f"sentinel_contract_{uuid.uuid4().hex[:8]}"


# -- backends -------------------------------------------------------------------


def _duckdb_csv(request: pytest.FixtureRequest, tmp_path: Path) -> Loader:
    def load(rows: list[Row]) -> DataSource:
        path = tmp_path / f"{_unique_name()}.csv"
        with path.open("w", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["id", "name", "amount", "created_at"])
            for id_, name, amount, at in rows:
                writer.writerow([id_, name or "", "" if amount is None else amount, at.isoformat()])
        return DuckDBSource(str(path))

    return load


def _duckdb_parquet(request: pytest.FixtureRequest, tmp_path: Path) -> Loader:
    import duckdb

    def load(rows: list[Row]) -> DataSource:
        path = tmp_path / f"{_unique_name()}.parquet"
        con = duckdb.connect()
        con.execute(
            "CREATE TABLE t (id BIGINT, name VARCHAR, amount DOUBLE, created_at TIMESTAMPTZ)"
        )
        if rows:
            con.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
        con.execute(f"COPY t TO '{path}' (FORMAT parquet)")
        return DuckDBSource(str(path))

    return load


def _postgres(request: pytest.FixtureRequest, tmp_path: Path) -> Loader:
    import psycopg

    dsn = os.environ.get(
        "SENTINEL_TEST_POSTGRES_DSN", "postgresql://sentinel:sentinel@localhost:5432/sentinel"
    )
    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as exc:
        _unavailable("postgres", str(exc).splitlines()[0])
    request.addfinalizer(conn.close)

    def load(rows: list[Row]) -> DataSource:
        table = _unique_name()
        conn.execute(
            f'CREATE TABLE "{table}" (id BIGINT, name TEXT, amount DOUBLE PRECISION, '
            f"created_at TIMESTAMPTZ)"
        )
        request.addfinalizer(lambda: conn.execute(f'DROP TABLE IF EXISTS "{table}"'))
        with conn.cursor() as cur:
            cur.executemany(f'INSERT INTO "{table}" VALUES (%s, %s, %s, %s)', rows)
        return PostgresDataSource(f"{dsn}?table={table}")

    return load


def _mysql(request: pytest.FixtureRequest, tmp_path: Path) -> Loader:
    pymysql = _driver("mysql", "pymysql", "mysql")
    url = os.environ.get(
        "SENTINEL_TEST_MYSQL_URL", "mysql://sentinel:sentinel@localhost:3306/sentinel"
    )
    from sentinel.datasources.mysql_source import _connection_args

    args, _ = _connection_args(f"{url}?table=unused")
    try:
        conn = pymysql.connect(**args)
    except pymysql.err.OperationalError as exc:
        _unavailable("mysql", str(exc))
    request.addfinalizer(conn.close)

    def load(rows: list[Row]) -> DataSource:
        table = _unique_name()
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE TABLE `{table}` (id BIGINT, name VARCHAR(50), amount DOUBLE, "
                f"created_at DATETIME)"
            )
            cur.executemany(
                f"INSERT INTO `{table}` VALUES (%s, %s, %s, %s)",
                [(i, n, a, at.replace(tzinfo=None)) for i, n, a, at in rows],
            )

        def drop() -> None:
            with conn.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS `{table}`")

        request.addfinalizer(drop)
        return MySQLDataSource(f"{url}?table={table}")

    return load


def _mongodb(request: pytest.FixtureRequest, tmp_path: Path) -> Loader:
    pymongo = _driver("mongodb", "pymongo", "mongodb")
    url = os.environ.get("SENTINEL_TEST_MONGODB_URL", "mongodb://localhost:27017/sentinel_test")
    client = pymongo.MongoClient(url, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
    except pymongo.errors.PyMongoError as exc:
        _unavailable("mongodb", str(exc).split(" (configured")[0])
    request.addfinalizer(client.close)
    database = client.get_default_database()

    def load(rows: list[Row]) -> DataSource:
        name = _unique_name()
        documents = []
        for id_, n, amount, at in rows:
            doc: dict[str, Any] = {"id": id_, "name": n, "created_at": at}
            if amount is not None:  # missing field, which must count as null
                doc["amount"] = amount
            documents.append(doc)
        if documents:
            database[name].insert_many(documents)
        else:
            database.create_collection(name)
        request.addfinalizer(lambda: database.drop_collection(name))
        return MongoDataSource(f"{url}{'&' if '?' in url else '?'}collection={name}")

    return load


def _snowflake(request: pytest.FixtureRequest, tmp_path: Path) -> Loader:
    url = os.environ.get("SENTINEL_TEST_SNOWFLAKE_URL")
    if not url:
        _unavailable("snowflake", "SENTINEL_TEST_SNOWFLAKE_URL not set")
    connector = _driver("snowflake", "snowflake.connector", "snowflake")
    from sentinel.datasources.snowflake_source import _connection_args

    args, _ = _connection_args(f"{url}{'&' if '?' in url else '?'}table=unused")
    conn = connector.connect(**args)
    request.addfinalizer(conn.close)

    def load(rows: list[Row]) -> DataSource:
        table = _unique_name()
        cur = conn.cursor()
        cur.execute(
            f"CREATE TABLE {table} (id NUMBER, name TEXT, amount FLOAT, created_at TIMESTAMP_TZ)"
        )
        if rows:
            cur.executemany(f"INSERT INTO {table} VALUES (%s, %s, %s, %s)", rows)
        request.addfinalizer(lambda: conn.cursor().execute(f"DROP TABLE IF EXISTS {table}"))
        return SnowflakeDataSource(f"{url}{'&' if '?' in url else '?'}table={table}")

    return load


def _bigquery(request: pytest.FixtureRequest, tmp_path: Path) -> Loader:
    url = os.environ.get("SENTINEL_TEST_BIGQUERY_URL")
    if not url:
        _unavailable("bigquery", "SENTINEL_TEST_BIGQUERY_URL not set")
    bigquery = _driver("bigquery", "google.cloud.bigquery", "bigquery")
    project, dataset = url.removeprefix("bigquery://").split("?")[0].split("/")
    client = bigquery.Client(project=project)

    def load(rows: list[Row]) -> DataSource:
        table = f"`{project}`.`{dataset}`.`{_unique_name()}`"
        client.query(
            f"CREATE TABLE {table} (id INT64, name STRING, amount FLOAT64, created_at TIMESTAMP)"
        ).result()
        request.addfinalizer(lambda: client.query(f"DROP TABLE IF EXISTS {table}").result())
        if rows:
            values = ", ".join(
                f"({i}, {'NULL' if n is None else repr(n)}, {'NULL' if a is None else a}, "
                f"TIMESTAMP '{at.isoformat()}')"
                for i, n, a, at in rows
            )
            client.query(f"INSERT INTO {table} VALUES {values}").result()
        name = table.split("`.`")[-1].strip("`")
        return BigQueryDataSource(f"bigquery://{project}/{dataset}?table={name}")

    return load


_BACKENDS: dict[str, Backend] = {
    "duckdb-csv": _duckdb_csv,
    "duckdb-parquet": _duckdb_parquet,
    "postgres": _postgres,
    "mysql": _mysql,
    "mongodb": _mongodb,
    "snowflake": _snowflake,
    "bigquery": _bigquery,
}


@pytest.fixture(params=list(_BACKENDS))
def load(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Loader]:
    yield _BACKENDS[request.param](request, tmp_path)


# -- the contract ---------------------------------------------------------------


def test_row_count(load: Loader) -> None:
    assert load(_ROWS).row_count() == 4


def test_null_count_counts_nulls_and_missing_values(load: Loader) -> None:
    source = load(_ROWS)
    assert source.null_count("name") == 1
    assert source.null_count("amount") == 1
    assert source.null_count("id") == 0


def test_distinct_count_excludes_nulls(load: Loader) -> None:
    source = load(_ROWS)
    assert source.distinct_count("name") == 2
    assert source.distinct_count("id") == 4


def test_max_value_ignores_nulls(load: Loader) -> None:
    source = load(_ROWS)
    assert source.max_value("id") == 4
    assert source.max_value("amount") == 30.25


def test_max_timestamp_is_utc_aware(load: Loader) -> None:
    latest = load(_ROWS).max_value("created_at")
    assert isinstance(latest, datetime)
    assert latest.utcoffset() == timedelta(0)
    assert latest == _NOW - timedelta(minutes=1)


def test_columns_use_canonical_types(load: Loader) -> None:
    columns = load(_ROWS).columns()
    assert {name: columns.get(name) for name in _EXPECTED_COLUMNS} == _EXPECTED_COLUMNS


def test_an_empty_dataset_is_ordinary(load: Loader) -> None:
    source = load([])
    assert source.row_count() == 0
    assert source.null_count("name") == 0
    assert source.distinct_count("name") == 0
    assert source.max_value("created_at") is None
