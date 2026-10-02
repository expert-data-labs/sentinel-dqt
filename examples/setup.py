"""Prepare the examples that need more than a CSV file.

    uv run python -m examples.setup

1. signups: backfills 28 days of history, so the adaptive threshold rules
   have something to compare against on the first real run. Values follow a
   weekly pattern (~1000 on weekdays, ~520 at weekends). Existing signups runs
   are replaced.
2. events: (re)creates the ``sentinel_examples`` database and loads an
   ``events`` table with timestamps from the last 30 minutes.

Needs the store to be migrated (``sentinel db upgrade``) and Postgres running.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from sentinel.dataset_loader import load_dataset
from sentinel.domain import Metric, QualityEvent, Status, ThresholdResult, ValidationRun
from sentinel.persistence import migrate
from sentinel.persistence.engine import StoreConnection, connect
from sentinel.persistence.writer import persist_validation_run
from sentinel.policy_loader import load_policy

REPO_ROOT = Path(__file__).parents[1]
EXAMPLES_DATABASE_URL = "postgresql://sentinel:sentinel@localhost:5432/sentinel_examples"

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


def main() -> None:
    with connect() as conn:
        if migrate.current_revision(conn) != migrate.head_revision():
            raise SystemExit("The store isn't migrated. Run `uv run sentinel db upgrade` first.")
        runs = seed_signups_history(conn)
    print(f"signups: backfilled {runs} days of history")

    load_events_table()
    print("events:  loaded 500 events into sentinel_examples.events")
    print("\nNext: uv run sentinel validate signups   (see docs/examples.md)")


if __name__ == "__main__":
    main()
