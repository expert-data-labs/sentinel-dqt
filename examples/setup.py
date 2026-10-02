"""Prepare the examples that need more than a CSV file.

    uv run python -m examples.setup

1. signups: backfills 28 days of history, so the adaptive threshold rules
   have something to compare against on the first real run. Values follow a
   weekly pattern (~1000 on weekdays, ~520 at weekends). Existing signups runs
   are replaced.
2. events: (re)creates the ``sentinel_examples`` Postgres database and loads
   an ``events`` table with timestamps from the last 30 minutes.
3. shipments: a MySQL table (two orders shipped twice).
4. reviews: a MongoDB collection (some reviews without a comment).
5. clickstream: a Parquet file in data/generated/.

Needs the store to be migrated (``sentinel db upgrade``) and the docker compose
services running. MySQL and MongoDB examples are skipped, with a hint, if their
service or driver isn't available.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from sentinel.dataset_loader import load_dataset
from sentinel.datasources._common import MissingDriverError, import_driver
from sentinel.domain import Metric, QualityEvent, Status, ThresholdResult, ValidationRun
from sentinel.persistence import migrate
from sentinel.persistence.engine import StoreConnection, connect
from sentinel.persistence.writer import persist_validation_run
from sentinel.policy_loader import load_policy

REPO_ROOT = Path(__file__).parents[1]
EXAMPLES_DATABASE_URL = "postgresql://sentinel:sentinel@localhost:5432/sentinel_examples"
EXAMPLES_MYSQL_URL = "mysql://sentinel:sentinel@localhost:3306/sentinel"
EXAMPLES_MONGODB_URL = "mongodb://localhost:27017/sentinel_examples"
CLICKSTREAM_PATH = REPO_ROOT / "data" / "generated" / "clickstream.parquet"

_HISTORY_DAYS = 28
_SEED = 42


def _daily_signups(day: datetime, rng: random.Random) -> float:
    """Simulated signup count for ``day``: weekly pattern plus small noise."""
    if day.weekday() < 5:
        return float(round(1000 + rng.uniform(-25, 25)))
    return float(round(520 + rng.uniform(-15, 15)))


def seed_signups_history(
    conn: StoreConnection, *, days: int = _HISTORY_DAYS, now: datetime | None = None
) -> int:
    """Replace the signups history with ``days`` backfilled daily runs. Returns runs written.

    Every rule in policies/signups.yaml gets the same daily value, recorded as
    a passing static check, which is what those rules would have seen had they
    started on a static threshold (the recommended cold start).
    """
    dataset = load_dataset(REPO_ROOT / "datasets" / "signups.yaml")
    policy = load_policy(REPO_ROOT / "policies" / "signups.yaml")
    now = now or datetime.now(UTC)
    rng = random.Random(_SEED)

    conn.execute("DELETE FROM validation_runs WHERE dataset_id = %s", (dataset.id,))
    for days_ago in range(days, 0, -1):
        day = now - timedelta(days=days_ago)
        value = _daily_signups(day, rng)
        events = tuple(
            QualityEvent(
                severity=rule.severity,
                blocking=rule.blocking,
                metric=Metric(metric_name=rule.name, value=value, computed_at=day),
                threshold_result=ThresholdResult(
                    status=Status.PASS, expected="backfilled history", strategy_type="static"
                ),
            )
            for rule in policy.rules
        )
        run = ValidationRun(
            dataset=dataset,
            policy_version="backfill",
            started_at=day,
            finished_at=day,
            status=Status.PASS,
            quality_events=events,
        )
        persist_validation_run(conn, run)
    return days


def load_events_table(url: str = EXAMPLES_DATABASE_URL, *, rows: int = 500) -> None:
    """Recreate the examples database and load ``rows`` recent events (1% anonymous)."""
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    with psycopg.connect(urlunsplit(parts._replace(path="/postgres")), autocommit=True) as admin:
        ident = sql.Identifier(name)
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(ident))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(ident))

    rng = random.Random(_SEED)
    now = datetime.now(UTC)
    anonymous = set(rng.sample(range(1, rows + 1), rows // 100))
    event_types = ["page_view"] * 6 + ["click"] * 3 + ["purchase"]
    data = [
        (
            event_id,
            None if event_id in anonymous else f"U{rng.randint(1, 200):04d}",
            rng.choice(event_types),
            now - timedelta(seconds=rng.randint(0, 30 * 60)),
        )
        for event_id in range(1, rows + 1)
    ]
    with psycopg.connect(url) as conn:
        conn.execute(
            """
            CREATE TABLE events (
                event_id    BIGINT PRIMARY KEY,
                user_id     TEXT,
                event_type  TEXT NOT NULL,
                occurred_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO events VALUES (%s, %s, %s, %s)", data)


def load_shipments_table(url: str = EXAMPLES_MYSQL_URL, *, rows: int = 300) -> None:
    """Recreate a MySQL ``shipments`` table. Orders 17 and 42 are shipped twice."""
    from sentinel.datasources.mysql_source import _connection_args

    pymysql = import_driver("pymysql", "mysql")
    args, _ = _connection_args(f"{url}?table=shipments")
    rng = random.Random(_SEED)
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    carriers = ["DHL", "FedEx", "UPS", "BlueDart"]
    order_ids = list(range(1, rows - 1)) + [17, 42]
    data = [
        (
            shipment_id,
            order_id,
            None if rng.random() < 0.02 else rng.choice(carriers),
            round(rng.uniform(0.2, 30), 2),
            rng.random() < 0.4,
            now - timedelta(minutes=rng.randint(0, 90)),
        )
        for shipment_id, order_id in enumerate(order_ids, start=1)
    ]
    conn = pymysql.connect(**args)
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS shipments")
            cur.execute(
                """
                CREATE TABLE shipments (
                    shipment_id BIGINT PRIMARY KEY,
                    order_id    BIGINT NOT NULL,
                    carrier     VARCHAR(20),
                    weight_kg   DECIMAL(6, 2) NOT NULL,
                    insured     BOOLEAN NOT NULL,
                    shipped_at  DATETIME NOT NULL
                )
                """
            )
            cur.executemany("INSERT INTO shipments VALUES (%s, %s, %s, %s, %s, %s)", data)
    finally:
        conn.close()


def load_reviews_collection(url: str = EXAMPLES_MONGODB_URL, *, documents: int = 200) -> None:
    """Recreate a MongoDB ``reviews`` collection. ~20% of reviews have no comment field."""
    pymongo = import_driver("pymongo", "mongodb")
    rng = random.Random(_SEED)
    now = datetime.now(UTC)
    docs = []
    for review_id in range(1, documents + 1):
        doc = {
            "review_id": review_id,
            "product_sku": f"SKU-{rng.randint(1, 30):04d}",
            "rating": rng.choice([1, 2, 3, 4, 4, 5, 5, 5]),
            "author": {
                "name": f"user{rng.randint(1, 500)}",
                "country": rng.choice(["IN", "US", "DE", "BR"]),
            },
            "created_at": now - timedelta(hours=rng.randint(0, 72)),
        }
        if rng.random() > 0.2:  # the rest have no comment field at all
            doc["comment"] = rng.choice(["Great", "Works as described", "Too small", "Love it"])
        docs.append(doc)
    docs[-1]["created_at"] = now - timedelta(minutes=5)  # newest review is recent
    client = pymongo.MongoClient(url, serverSelectionTimeoutMS=3000)
    try:
        collection = client.get_default_database()["reviews"]
        collection.drop()
        collection.insert_many(docs)
    finally:
        client.close()


def write_clickstream_parquet(path: Path = CLICKSTREAM_PATH, *, rows: int = 5000) -> None:
    """Write a Parquet file of page events with exact column types."""
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(path).replace("'", "''")
    duckdb.execute(
        f"""
        COPY (
            SELECT i::BIGINT AS event_id,
                   'S' || lpad(((i * 7919) % 900)::VARCHAR, 4, '0') AS session_id,
                   ['/home', '/search', '/product', '/cart', '/checkout'][1 + i % 5] AS page,
                   (50 + (i * 37) % 4000)::INTEGER AS duration_ms,
                   now() - to_seconds(i * 3) AS occurred_at
            FROM range(1, {rows + 1}) t(i)
        ) TO '{escaped}' (FORMAT parquet)
        """
    )


def _try(label: str, load: Callable[[], None], hint: str) -> None:
    """Run one optional loader, reporting rather than failing if its service is missing."""
    try:
        load()
    except MissingDriverError as exc:
        print(f"{label}skipped: {exc}")
    except Exception as exc:  # noqa: BLE001 - any connection error just means "not running"
        print(f"{label}skipped ({type(exc).__name__}: {str(exc).splitlines()[0][:80]}). {hint}")
    else:
        print(f"{label}loaded")


def main() -> None:
    with connect() as conn:
        if migrate.current_revision(conn) != migrate.head_revision():
            raise SystemExit("The store isn't migrated. Run `uv run sentinel db upgrade` first.")
        runs = seed_signups_history(conn)
    print(f"signups: backfilled {runs} days of history")

    load_events_table()
    print("events:      loaded 500 events into sentinel_examples.events (Postgres)")

    compose = "Start it with `docker compose up -d`."
    _try("shipments:   ", load_shipments_table, compose)
    _try("reviews:     ", load_reviews_collection, compose)
    _try("clickstream: ", write_clickstream_parquet, "")
    print("\nNext: uv run sentinel validate signups   (see docs/examples.md)")


if __name__ == "__main__":
    main()
