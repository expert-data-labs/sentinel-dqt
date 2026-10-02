# Examples: a guided tour of Sentinel

The repository ships eight example datasets and a simulator. Together they exercise every rule, every threshold strategy, every kind of data source, blocking and non-blocking rules, and the incident, history and dashboard features. Each dataset is a YAML file in `datasets/` and a policy in `policies/`; CSV data lives in `data/`.

| Dataset | Source | Shows | Expected result |
|---|---|---|---|
| `customers` | CSV | A clean dataset; null rate, uniqueness and schema rules passing | Exit `0`, all ✓ |
| `products` | CSV | Blocking vs non-blocking rules; info severity; low criticality | Exit `0`, one ✗ with an incident |
| `orders` | CSV | All five rule types failing; incidents; stale data | Exit `2` (blocking failure) |
| `signups` | CSV + backfilled history | All four adaptive threshold strategies compared on the same metric | Exit `0`; verdicts differ by strategy and weekday |
| `events` | Postgres table | The Postgres adapter; freshness and schema passing | Exit `0`, all ✓ |
| `shipments` | MySQL table | `${MYSQL_PASSWORD}` in config; a real duplicate caught | Exit `2` |
| `reviews` | MongoDB collection | Missing fields count as null; dotted paths into sub-documents | Exit `0`, all ✓ |
| `clickstream` | Parquet file | Exact column types from Parquet | Exit `0`, all ✓ |
| `simulated_orders` | Any of the above | **The simulator:** 8 weeks replayed with injected anomalies, scored per strategy | A scorecard |

The [guided demo](../demo/run_demo.sh) adds a CRITICAL dataset that degrades over four simulated days, for CRITICAL incidents and recurring failures.

---

## 1. Set up (once)

```bash
uv sync --all-groups --all-extras    # includes the MySQL and MongoDB drivers
docker compose up -d                  # local Postgres, MySQL and MongoDB
uv run sentinel db upgrade            # create the store's schema
export MYSQL_PASSWORD=sentinel        # read by datasets/shipments.yaml
uv run python -m examples.setup       # history backfill + example tables
```

`examples.setup` prepares the examples that need more than a CSV file. MySQL and MongoDB are skipped, with a hint, if their service or driver isn't available.

- **Backfills 28 days of `signups` history.** Adaptive strategies compare today against past runs, and refuse to judge (and abort the run) until they have enough. The backfill follows a weekly pattern: about 1000 signups on weekdays and 520 at weekends. Running it again replaces any `signups` history.
- **Loads `events` into Postgres:** a `sentinel_examples` database with an `events` table of 500 events from the last 30 minutes, 1% of them anonymous.
- **Loads `shipments` into MySQL** (300 rows; orders 17 and 42 shipped twice), **`reviews` into MongoDB** (200 documents, ~20% without a comment), and writes **`data/generated/clickstream.parquet`** (5000 events).

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

## 7. MySQL, with secrets from the environment: `shipments`

```bash
uv run sentinel validate shipments
```

`datasets/shipments.yaml` reads `mysql://sentinel:${MYSQL_PASSWORD}@localhost:3306/sentinel?table=shipments`. The password is filled in from the environment when the run starts, and only the `${...}` form is stored. Unset the variable and rerun to see the error name it.

Two orders were shipped twice, so `one_shipment_per_order` fails and the command exits `2`. The schema rule passes, including `insured`, a MySQL `BOOLEAN` (`tinyint(1)`) reported as `boolean`.

## 8. Documents: `reviews` in MongoDB

```bash
uv run sentinel validate reviews
```

About 20% of reviews have no `comment` field at all. For MongoDB a missing field counts as null, so `comment_present` reports a null rate near `0.2` (allowed up to `0.3`). `author_country_known` checks `author.country`, a dotted path into each review's `author` sub-document.

## 9. Parquet: `clickstream`

```bash
uv run sentinel validate clickstream
```

Parquet files carry exact column types, so the schema rule needs no guesswork (compare `orders`, where DuckDB infers types from CSV text). The same dataset could point at `data/generated/*.parquet` or `s3://bucket/clickstream/*.parquet`.

---

## 10. Testing adaptive thresholds with the simulator

The `signups` example shows one day. To see how strategies behave **over time** (warm-up, seasonality, growth, and what an anomaly does to the history that follows), replay weeks of loads through the real pipeline:

```bash
uv run python -m examples.simulate                    # 8 weeks into a CSV file (DuckDB)
uv run python -m examples.simulate --source postgres  # or mysql, mongodb
```

For each simulated day the simulator:

1. generates that day's orders: ~1000 on weekdays and ~550 at weekends, growing 0.3% a day, with ±3% noise and ~0.5% missing customer ids;
2. loads them into the chosen source, replacing the previous day's;
3. runs `policies/simulated_orders.yaml` through the same `validate_and_record()` the CLI uses, with Sentinel's clock pinned to that day. Runs are stored, so each adaptive strategy reads its history through its real query, exactly as in production.

The first 14 days run every rule on a permissive static threshold to build history (the recommended [cold start](components/thresholds.md#cold-start)). Then the real policy takes over, and four anomalies are injected on known days:

| Anomaly | What happens | Who should catch it |
|---|---|---|
| Duplicate load | Volume +60% | Volume rules |
| Partial load | Volume −55% | Volume rules |
| Weekday at weekend volume | A weekday arrives at ~550 rows | Only a weekday-aware strategy |
| Null spike | 8% of customer ids missing | Null-rate rules |

The scorecard (default seed, 42 evaluated days):

```text
rule                  strategy                caught  missed  false alarms
volume_static         static                     1/3       2             4
volume_pct_of_mean    percentage_deviation       2/3       1            22
volume_statistical    statistical                0/3       3             0
volume_median_mad     median_mad                 2/3       1            11
volume_seasonal       seasonal                   3/3       0             5
nulls_static          static                     1/1       0             0
nulls_statistical     statistical                1/1       0             0
nulls_median_mad      median_mad                 1/1       0             0
```

followed by a timeline, one row per rule and one column per day (`#` caught, `x` false alarm, `!` missed, `.` quiet).

How to read it:

- **seasonal** is the only volume strategy that catches all three, including the weekday that arrived at weekend volume. Its false alarms cluster in the first evaluated week, when each weekday has only two past points and the band is very tight.
- **statistical** catches nothing: the weekday/weekend swing makes its band so wide that even a 60% jump fits inside.
- **percentage_deviation** compares against the mean of all days, so it fires on weekends, and as volume grows, the lagging mean makes it fire on weekdays too.
- **median_mad** locks onto the weekday level and calls every weekend an anomaly.
- **The null rate** has no weekly pattern, so every strategy catches the spike with no false alarms. Seasonality is what separates the strategies.

Things to try (edit the policy, rerun, compare):

- Give seasonal more history: `--warmup 28 --days 70`. With four past points per weekday it catches all three anomalies with **zero** false alarms; its earlier false alarms came only from thin history. (Raising its `min_history` to 4 needs the same longer warm-up; with too little history the simulator stops and says so, because an adaptive rule without enough history aborts a real run too.)
- Tighten `volume_statistical` to `n_sigma: 1.5`. It now catches the partial load with a single false alarm, but still misses the duplicate load and the weekday gap: a narrower band doesn't fix a baseline that ignores the weekly pattern.
- Run longer (`--days 112`) and watch `volume_pct_of_mean` degrade as growth outpaces its baseline.
- Try another `--seed`, or another `--source`: the scorecard is identical on every source, because the adapters agree on the data.

The runs stay in the store as dataset `simulated_orders_<source>`: browse them with `uv run sentinel history simulated_orders_duckdb --limit 60`, or pick the dataset in the dashboard's Metric Trends to see the weekly pattern and the anomalies.

For a purely statistical comparison of the strategies on more scenarios, without the pipeline, see the [threshold strategy evaluation](experiments/threshold-strategy-evaluation.md).

---

## 11. History and the dashboard

```bash
uv run sentinel history signups          # 28 backfilled runs + today's
uv sync --group dashboard
uv run streamlit run dashboard/app.py
```

The dashboard shows every dataset's health, recent incidents, failed and recurring rules, and per-rule metric trends. For `signups`, pick a rule under Metric Trends to see the weekly pattern in its history.

## 12. Running validations concurrently

Every `sentinel validate` call can run at the same time as any other:

```bash
for d in customers products orders signups events shipments reviews clickstream; do uv run sentinel validate $d & done; wait
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
| Data sources: Parquet, MySQL, MongoDB | `clickstream`, `shipments`, `reviews` |
| Data sources: JSON, S3, Snowflake, BigQuery | [Data Sources: configuration per source](components/data-sources.md#configuration-per-source) |
| Secrets as `${ENV_VAR}` | `shipments` |
| Adaptive strategies over time, scored against known anomalies | `python -m examples.simulate` |
| Blocking vs non-blocking rules, exit codes `0` and `2` | `products`, `orders` |
| Store not migrated, exit code `3` | Run any `validate` against an empty database |
| Severity (`info` to `critical`) and criticality (`low` to `critical`) | `products` (info, low), `customers` (medium), `orders` (high), `demo/` (critical) |
| Incidents, priorities and reasons | `orders`, `products`, `signups` |
| Recurring and persistent failures | `orders` run several times, or `demo/run_demo.sh` |
| Policy versioning | `customers` (`version:` in the policy) |
| Run history and dashboard | `sentinel history <dataset>`, `dashboard/app.py` |

Exit code `1` (warnings) exists, but none of the built-in strategies produces a WARN, so no example shows it.
