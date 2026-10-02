"""Replay weeks of daily loads through the real pipeline to test threshold strategies.

    uv run python -m examples.simulate                    # 8 weeks into a CSV file (DuckDB)
    uv run python -m examples.simulate --source postgres  # or mysql, mongodb
    uv run python -m examples.simulate --days 84 --seed 3

For each simulated day, the simulator generates that day's orders (a weekly
pattern, slow growth, noise, and anomalies injected on known days), loads them
into the chosen source, and runs ``policies/simulated_orders.yaml`` through
``validate_and_record`` with the clock pinned to that day. History builds up in
Sentinel's store exactly as in production, and adaptive strategies read it
through their real queries.

The first ``--warmup`` days run every rule on a permissive static threshold to
build history (the recommended cold start). After that the real policy runs,
and a scorecard compares each rule's verdicts with the injected anomalies.
Results stay in the store as dataset ``simulated_orders_<source>``, for
``sentinel history`` and the dashboard.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sentinel import clock
from sentinel.datasources import get_data_source
from sentinel.datasources._common import import_driver
from sentinel.domain import Criticality, Dataset, Policy, Status, ThresholdConfig
from sentinel.persistence import migrate
from sentinel.persistence.engine import StoreConnection, connect
from sentinel.policy_loader import load_policy
from sentinel.registration import register_all
from sentinel.thresholds import InsufficientHistoryError
from sentinel.validation_service import validate_and_record

REPO_ROOT = Path(__file__).parents[1]
POLICY_PATH = REPO_ROOT / "policies" / "simulated_orders.yaml"
SOURCES = ("duckdb", "postgres", "mysql", "mongodb")

# Which anomaly kind each rule type is meant to catch.
_WATCHES = {"row_count": "volume", "null_rate": "nulls"}

Row = tuple[int, str | None, float, datetime]


# -- the scenario ---------------------------------------------------------------


@dataclass(frozen=True)
class SimDay:
    """One simulated daily load and the anomalies injected into it (ground truth)."""

    index: int
    at: datetime
    rows: int
    null_rate: float
    anomalies: frozenset[str] = frozenset()
    note: str = ""


def generate_scenario(days: int, warmup: int, seed: int, end: datetime) -> list[SimDay]:
    """Daily volumes with a weekly pattern, 0.3%/day growth and +/-3% noise, ending at ``end``.

    Four anomalies are injected after the warm-up, spread across the
    evaluation window:

    - duplicate load: volume +60%
    - partial load: volume -55%
    - weekday batch missing: a weekday arrives at weekend volume (only a
      weekday-aware strategy should catch this one)
    - null spike: 8% of customer ids missing (normally ~0.5%)
    """
    if days - warmup < 10:
        raise ValueError("Need at least 10 days after the warm-up to place the anomalies")
    rng = random.Random(seed)
    start = end - timedelta(days=days - 1)
    span = days - warmup

    def at(fraction: float) -> int:
        return warmup + int(span * fraction)

    spike, drop, null_spike = at(0.2), at(0.4), at(0.85)
    weekday_gap = next(i for i in range(at(0.6), days) if (start + timedelta(days=i)).weekday() < 5)

    scenario = []
    for i in range(days):
        day = start + timedelta(days=i)
        weekend = day.weekday() >= 5
        level = (550 if weekend else 1000) * 1.003**i
        rows = level * rng.uniform(0.97, 1.03)
        null_rate = max(0.0, rng.gauss(0.005, 0.0015))
        anomalies: set[str] = set()
        note = ""
        if i == spike:
            rows, note = rows * 1.6, "duplicate load (+60%)"
        elif i == drop:
            rows, note = rows * 0.45, "partial load (-55%)"
        elif i == weekday_gap:
            rows, note = 550 * 1.003**i * rng.uniform(0.97, 1.03), "weekday at weekend volume"
        if note:
            anomalies.add("volume")
        if i == null_spike:
            null_rate, note = 0.08, "customer_id nulls 8%"
            anomalies.add("nulls")
        scenario.append(SimDay(i, day, round(rows), null_rate, frozenset(anomalies), note))
    return scenario


def rows_for(day: SimDay, rng: random.Random) -> list[Row]:
    """The orders loaded on ``day``."""
    return [
        (
            order_id,
            None if rng.random() < day.null_rate else f"C{rng.randint(1, 5000):05d}",
            round(rng.uniform(5, 300), 2),
            day.at - timedelta(seconds=rng.randint(0, 86_399)),
        )
        for order_id in range(1, day.rows + 1)
    ]


# -- loading each day into a source ----------------------------------------------


@dataclass
class Loader:
    """Replaces the dataset's content with one day's rows; knows its config_reference."""

    config_reference: str
    load: Callable[[list[Row]], None]
    close: Callable[[], None] = field(default=lambda: None)


def _duckdb_loader() -> Loader:
    path = REPO_ROOT / "data" / "generated" / "simulated_orders.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    def load(rows: list[Row]) -> None:
        with path.open("w", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["order_id", "customer_id", "amount", "created_at"])
            for order_id, customer, amount, at in rows:
                writer.writerow([order_id, customer or "", amount, at.isoformat()])

    return Loader(str(path), load)


def _postgres_loader() -> Loader:
    import psycopg
    from psycopg import sql

    url = os.environ.get(
        "SENTINEL_EXAMPLES_DATABASE_URL",
        "postgresql://sentinel:sentinel@localhost:5432/sentinel_examples",
    )
    server, _, name = url.rpartition("/")
    with psycopg.connect(f"{server}/postgres", autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    conn = psycopg.connect(url, autocommit=True)
    conn.execute("DROP TABLE IF EXISTS simulated_orders")
    conn.execute(
        "CREATE TABLE simulated_orders (order_id BIGINT, customer_id TEXT, "
        "amount DOUBLE PRECISION, created_at TIMESTAMPTZ)"
    )

    def load(rows: list[Row]) -> None:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("TRUNCATE simulated_orders")
            with cur.copy("COPY simulated_orders FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)

    return Loader(f"{url}?table=simulated_orders", load, conn.close)


def _mysql_loader() -> Loader:
    from sentinel.datasources.mysql_source import _connection_args

    pymysql = import_driver("pymysql", "mysql")
    os.environ.setdefault("MYSQL_PASSWORD", "sentinel")  # the docker compose default
    url = "mysql://sentinel:${MYSQL_PASSWORD}@localhost:3306/sentinel"
    args, _ = _connection_args(
        url.replace("${MYSQL_PASSWORD}", os.environ["MYSQL_PASSWORD"]) + "?table=x"
    )
    conn = pymysql.connect(**args)
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS simulated_orders")
        cur.execute(
            "CREATE TABLE simulated_orders (order_id BIGINT, customer_id VARCHAR(10), "
            "amount DOUBLE, created_at DATETIME)"
        )

    def load(rows: list[Row]) -> None:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE simulated_orders")
            cur.executemany(
                "INSERT INTO simulated_orders VALUES (%s, %s, %s, %s)",
                [(o, c, a, at.astimezone(UTC).replace(tzinfo=None)) for o, c, a, at in rows],
            )

    return Loader(f"{url}?table=simulated_orders", load, conn.close)


def _mongodb_loader() -> Loader:
    pymongo = import_driver("pymongo", "mongodb")
    url = "mongodb://localhost:27017/sentinel_examples"
    client = pymongo.MongoClient(url, serverSelectionTimeoutMS=3000)
    collection = client.get_default_database()["simulated_orders"]

    def load(rows: list[Row]) -> None:
        collection.delete_many({})
        collection.insert_many(
            [
                {"order_id": o, "customer_id": c, "amount": a, "created_at": at}
                for o, c, a, at in rows
            ]
        )

    return Loader(f"{url}?collection=simulated_orders", load, client.close)


_LOADERS: dict[str, Callable[[], Loader]] = {
    "duckdb": _duckdb_loader,
    "postgres": _postgres_loader,
    "mysql": _mysql_loader,
    "mongodb": _mongodb_loader,
}


# -- running and scoring ----------------------------------------------------------


@dataclass
class Outcome:
    """Each rule's verdict on each simulated day."""

    day: SimDay
    statuses: dict[str, Status]


def warmup_policy(policy: Policy) -> Policy:
    """The same rules (same names, so the same history) on a static threshold that always passes."""
    permissive = ThresholdConfig(strategy="static", params={"min": 0})
    return policy.model_copy(
        update={
            "rules": tuple(r.model_copy(update={"threshold": permissive}) for r in policy.rules)
        }
    )


def simulate(
    conn: StoreConnection,
    source: str = "duckdb",
    *,
    days: int = 56,
    warmup: int = 14,
    seed: int = 7,
    policy_path: Path = POLICY_PATH,
    end: datetime | None = None,
    progress: Callable[[str], None] = lambda message: None,
) -> tuple[list[Outcome], Policy]:
    """Replay ``days`` daily loads into ``source``. Returns every day's verdicts and the policy."""
    register_all()
    policy = load_policy(policy_path)
    scenario = generate_scenario(
        days,
        warmup,
        seed,
        end or datetime.now(UTC).replace(hour=6, minute=0, second=0, microsecond=0),
    )
    loader = _LOADERS[source]()
    dataset = Dataset(
        id=f"simulated_orders_{source}",
        name=f"simulated_orders_{source}",
        source_type=source,
        environment="simulation",
        owner="data-platform-team",
        criticality=Criticality.HIGH,
        config_reference=loader.config_reference,
    )
    conn.execute("DELETE FROM validation_runs WHERE dataset_id = %s", (dataset.id,))

    rng = random.Random(seed)
    warm, real = warmup_policy(policy), policy
    outcomes: list[Outcome] = []
    try:
        for day in scenario:
            loader.load(rows_for(day, rng))
            data_source = get_data_source(dataset.source_type, dataset.config_reference)
            with clock.frozen_at(day.at):
                run, _ = validate_and_record(
                    conn, dataset, warm if day.index < warmup else real, data_source
                )
            outcomes.append(Outcome(day, {e.rule_name: e.status for e in run.quality_events}))
            progress(f"day {day.index + 1}/{days} {day.at:%a %d %b}: {day.rows} rows")
    finally:
        loader.close()
    return outcomes[warmup:], policy


@dataclass(frozen=True)
class Score:
    """One rule's results over the evaluated days."""

    rule: str
    strategy: str
    caught: int
    missed: int
    false_alarms: int
    quiet_days: int


def score(outcomes: Sequence[Outcome], policy: Policy) -> list[Score]:
    """Compare each rule's verdicts with the anomalies it is meant to catch."""
    scores = []
    for rule in policy.rules:
        kind = _WATCHES.get(rule.rule_type)
        caught = missed = false_alarms = quiet = 0
        for outcome in outcomes:
            flagged = outcome.statuses[rule.name] is not Status.PASS
            anomalous = kind in outcome.day.anomalies
            if flagged and anomalous:
                caught += 1
            elif anomalous:
                missed += 1
            elif flagged:
                false_alarms += 1
            else:
                quiet += 1
        scores.append(
            Score(rule.name, rule.threshold.strategy, caught, missed, false_alarms, quiet)
        )
    return scores


def render(outcomes: Sequence[Outcome], policy: Policy, source: str) -> str:
    """The scorecard and a day-by-day timeline as plain text."""
    lines = [
        f"Simulated {len(outcomes)} evaluated days into {source} "
        f"({outcomes[0].day.at:%d %b} to {outcomes[-1].day.at:%d %b}).",
        "",
        "Injected anomalies:",
    ]
    for o in outcomes:
        if o.day.note:
            lines.append(f"  {o.day.at:%a %d %b}  {o.day.note}  ({o.day.rows} rows)")

    lines += ["", f"{'rule':<22}{'strategy':<22}{'caught':>8}{'missed':>8}{'false alarms':>14}"]
    for s in score(outcomes, policy):
        total = s.caught + s.missed
        lines.append(
            f"{s.rule:<22}{s.strategy:<22}{f'{s.caught}/{total}':>8}{s.missed:>8}{s.false_alarms:>14}"
        )

    weekdays = "".join("MTWTFSS"[o.day.at.weekday()] for o in outcomes)
    markers = "".join("^" if o.day.anomalies else " " for o in outcomes)
    lines += ["", "Timeline (# caught  x false alarm  ! missed  . quiet; ^ = anomaly day)"]
    lines += [f"{'':<22}{weekdays}", f"{'':<22}{markers}"]
    for rule in policy.rules:
        kind = _WATCHES.get(rule.rule_type)
        cells = []
        for o in outcomes:
            flagged = o.statuses[rule.name] is not Status.PASS
            anomalous = kind in o.day.anomalies
            cells.append(
                "#" if flagged and anomalous else "!" if anomalous else "x" if flagged else "."
            )
        lines.append(f"{rule.name:<22}{''.join(cells)}")
    lines += [
        "",
        f"Explore: uv run sentinel history simulated_orders_{source} --limit 60",
        "          uv run streamlit run dashboard/app.py   (Metric Trends, Recurring Failures)",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--source", choices=SOURCES, default="duckdb")
    parser.add_argument("--days", type=int, default=56, help="days to simulate (default 56)")
    parser.add_argument("--warmup", type=int, default=14, help="history-building days (default 14)")
    parser.add_argument("--seed", type=int, default=7, help="random seed (default 7)")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    args = parser.parse_args(argv)

    interactive = sys.stdout.isatty()
    with connect() as conn:
        if migrate.current_revision(conn) != migrate.head_revision():
            raise SystemExit("The store isn't migrated. Run `uv run sentinel db upgrade` first.")
        try:
            outcomes, policy = simulate(
                conn,
                args.source,
                days=args.days,
                warmup=args.warmup,
                seed=args.seed,
                policy_path=args.policy,
                progress=_progress if interactive else lambda message: None,
            )
        except InsufficientHistoryError as exc:
            raise SystemExit(
                f"\n{exc}\nThe warm-up didn't build enough history for this policy. "
                f"Raise --warmup (seasonal needs min_history weeks, e.g. --warmup "
                f"{7 * 4} for min_history: 4) or lower min_history."
            ) from None
    if interactive:
        print("\r" + " " * 60 + "\r", end="")  # clear the progress line
    print(render(outcomes, policy, args.source))


def _progress(message: str) -> None:
    """Overwrite one terminal line with the latest day."""
    print(f"\r{message:<60}", end="", flush=True)


if __name__ == "__main__":
    main()
