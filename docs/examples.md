# Examples: a guided tour of Sentinel

The repository ships five example datasets. Together they exercise every rule, every threshold strategy, both data sources, blocking and non-blocking rules, and the incident, history and dashboard features. Each one is a dataset YAML in `datasets/`, a policy in `policies/`, and (for CSV sources) a file in `data/`.

| Dataset | Source | Shows | Expected result |
|---|---|---|---|
| `customers` | CSV | A clean dataset; null rate, uniqueness and schema rules passing | Exit `0`, all ✓ |
| `products` | CSV | Blocking vs non-blocking rules; info severity; low criticality | Exit `0`, one ✗ with an incident |
| `orders` | CSV | All five rule types failing; incidents; stale data | Exit `2` (blocking failure) |
| `signups` | CSV + backfilled history | All four adaptive threshold strategies compared on the same metric | Exit `0`; verdicts differ by strategy and weekday |
| `events` | Postgres table | The Postgres adapter; freshness and schema passing | Exit `0`, all ✓ |

The [guided demo](../demo/run_demo.sh) adds a CRITICAL dataset that degrades over four simulated days, for CRITICAL incidents and recurring failures.

---

## 1. Set up (once)

```bash
uv sync --all-groups
docker compose up -d                  # local Postgres
uv run sentinel db upgrade            # create the store's schema
uv run python -m examples.setup       # signups history + the Postgres events table
```

`examples.setup` does two things:

- **Backfills 28 days of `signups` history.** Adaptive strategies compare today against past runs, and refuse to judge (and abort the run) until they have enough. The backfill follows a weekly pattern: about 1000 signups on weekdays and 520 at weekends. Running it again replaces any `signups` history.
- **Loads `events` into Postgres:** a `sentinel_examples` database with an `events` table of 500 events from the last 30 minutes, 1% of them anonymous.

---

## 2. What success looks like: `customers`

```bash
uv run sentinel validate customers
```

Four rules pass and the command exits `0`. The schema rule compares the CSV's columns and inferred types against `expected_schema` in `policies/customers.yaml`.

**Try:** blank one email in `data/customers.csv`, or duplicate a line, then rerun. The run fails with exit `2`, because `email_not_null` and `customer_id_unique` are blocking (the default).

## 3. Failing without stopping the pipeline: `products`

```bash
uv run sentinel validate products
```

6 of the 30 products have no description, so `description_not_null` fails (`0.2` against a limit of `0.05`). The rule is `blocking: false` and `severity: info`, so the command still exits `0`, but the failure is recorded with an incident. Its priority is WARNING despite the low criticality and info severity, because the null rate is four times the limit.

Use this pattern for checks you want to track but not enforce yet.

## 4. Everything broken: `orders`

```bash
uv run sentinel validate orders
```

A 12-row sample with too few rows, a missing `customer_id`, a duplicated order, stale timestamps (the freshness rule allows 60 minutes) and, depending on DuckDB's type inference, a schema difference. Every rule is blocking, so the command exits `2`. Each failure gets an incident with a priority, a score and the reasons behind it.

**Try:** run it three more times, then `uv run sentinel history orders`. In the dashboard (step 7) the same failures move from *first occurrence* to *persistent* under Recurring Failures, and their frequency scores rise.

## 5. Adaptive thresholds compared: `signups`

```bash
uv run sentinel validate signups
```

Today's file has 1000 signups. The policy checks that number five ways. One is a blocking static sanity check; the other four are adaptive strategies running as non-blocking "shadow" rules, so you can compare their verdicts without failing the pipeline:

| Rule | Strategy | Weekday run | Weekend run | Why |
|---|---|---|---|---|
| `row_count_sanity` | `static`, min 100 | ✓ | ✓ | Fixed floor |
| `row_count_vs_recent_mean` | `percentage_deviation`, ±10% | ✗ | ✗ | Baseline (~860) mixes weekdays and weekends, so it is wrong every day |
| `row_count_statistical` | `statistical`, ±3σ | ✓ | ✓ | The weekly swing makes the band roughly 190 to 1530: it would miss real problems too |
| `row_count_median_mad` | `median_mad`, ±3 MAD | ✓ | ✓ | Locks onto the weekday level (~985); a genuine weekend value of ~520 would fail |
| `row_count_seasonal` | `seasonal`, same weekday | ✓ | ✗ | Compares against the same weekday only: 1000 is normal on a Friday, abnormal on a Saturday |

Only the seasonal strategy understands the weekly pattern. The expected line in each result shows the band each strategy computed. For the full, controlled comparison see the [threshold strategy evaluation](experiments/threshold-strategy-evaluation.md).

**Try:**

- Simulate a weekend load on a weekday: `head -n 521 data/signups.csv > /tmp/s.csv && cp /tmp/s.csv data/signups.csv` (520 rows), then rerun. Seasonal now fails; on a weekend it would pass. Restore with `git checkout data/signups.csv`.
- Simulate an outage: keep 200 rows. Every adaptive strategy fails; the sanity check still passes.

## 6. Postgres as a data source: `events`

```bash
uv run sentinel validate events
```

The same rule types run against a Postgres table. The dataset's `config_reference` is a connection URL with the table as a parameter: `postgresql://…/sentinel_examples?table=events`. All five rules pass, including freshness (the newest event is minutes old) and schema (Postgres `bigint`, `text` and `timestamptz` map to `integer`, `string` and `timestamp`).

**Try:** wait an hour and rerun; freshness fails. `uv run python -m examples.setup` reloads fresh events.

## 7. History and the dashboard

```bash
uv run sentinel history signups          # 28 backfilled runs + today's
uv sync --group dashboard
uv run streamlit run dashboard/app.py
```

The dashboard shows every dataset's health, recent incidents, failed and recurring rules, and per-rule metric trends. For `signups`, pick a rule under Metric Trends to see the weekly pattern in its history.

## 8. Running validations concurrently

Every `sentinel validate` call can run at the same time as any other:

```bash
for d in customers products orders signups events; do uv run sentinel validate $d & done; wait
```

Different datasets run in parallel. Two runs of the **same** dataset are serialized, so the second sees the first one's results in its history (see [Persistence: concurrency](components/persistence.md#concurrency)).

---

## Feature checklist

| Feature | Where to see it |
|---|---|
| Rules: `row_count`, `null_rate`, `uniqueness`, `freshness`, `schema` | `orders` (all failing), `customers` and `events` (passing) |
| Strategies: `static` | every example |
| Strategies: `percentage_deviation`, `statistical`, `median_mad`, `seasonal` | `signups` |
| Data sources: CSV via DuckDB, Postgres | `customers`/`products`/`orders`/`signups`, `events` |
| Blocking vs non-blocking rules, exit codes `0` and `2` | `products`, `orders` |
| Store not migrated, exit code `3` | Run any `validate` against an empty database |
| Severity (`info` to `critical`) and criticality (`low` to `critical`) | `products` (info, low), `customers` (medium), `orders` (high), `demo/` (critical) |
| Incidents, priorities and reasons | `orders`, `products`, `signups` |
| Recurring and persistent failures | `orders` run several times, or `demo/run_demo.sh` |
| Policy versioning | `customers` (`version:` in the policy) |
| Run history and dashboard | `sentinel history <dataset>`, `dashboard/app.py` |

Exit code `1` (warnings) exists, but none of the built-in strategies produces a WARN, so no example shows it.
