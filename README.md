# Sentinel

**A configurable data reliability platform.** Sentinel lets data teams declare what "good data" means for each dataset in YAML, then validates every load against it, judges the results with static or history-aware thresholds, ranks failures by how much they matter, and keeps a queryable history of every run.

Pipelines call one command and act on its exit code:

```bash
sentinel validate orders    # exit 0 = pass, 2 = a blocking rule failed
```

![Sentinel architecture](docs/assets/architecture.svg)

---

## Why Sentinel

Quality checks usually live inside pipeline code: a `COUNT(*)` with an `assert`, a hard-coded threshold, no record of what yesterday looked like, and every failure equally loud. Sentinel separates those concerns:

| Concern | In Sentinel |
|---|---|
| **What to check** | Declared once per dataset in a policy file, reviewed like code |
| **How to measure it** | Reusable rules that work unchanged on files, Postgres, MySQL, Snowflake, BigQuery and MongoDB |
| **What counts as acceptable** | Pluggable threshold strategies, from fixed bounds to seasonal baselines learned from history |
| **Whether it matters** | Every failure becomes a prioritized, explained incident |
| **What happened before** | Every measurement, verdict and incident is persisted and queryable |

Measurements are stored separately from pass/fail verdicts. That is what makes adaptive thresholds, trend charts and replaying a stricter threshold against history possible.

## Features

- **Five rule types:** row count, null rate, uniqueness, freshness, schema validation
- **Six data sources:** files (CSV, Parquet, JSON; local or S3) through DuckDB, PostgreSQL, MySQL, Snowflake, BigQuery and MongoDB, with secrets supplied as `${ENV_VAR}`
- **Five threshold strategies:**
  - `static`
  - `percentage_deviation`
  - `statistical` (mean ± kσ)
  - `median_mad` (robust to outliers)
  - `seasonal` (per day of week)
- **Incident prioritization:** a deterministic, explainable score from severity, dataset criticality, deviation, failure frequency and anomaly confidence, bucketed into INFO, WARNING, HIGH or CRITICAL
- **Blocking-aware exit codes,** so a failure on a non-blocking rule is recorded without stopping the pipeline
- **Run history** in a shared PostgreSQL store, safe for simultaneous runs from many teams and pipelines, with versioned migrations, `sentinel history` and a read-only Streamlit dashboard
- **Extensible:** a new rule, strategy or data source is a new class plus one registration line, with no changes to existing code

---

## Quick start

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and Docker (for the local Postgres store).

```bash
git clone <this repo> && cd sentinel
uv sync
docker compose up -d            # local Postgres
uv run sentinel db upgrade      # create the store's schema (once)
uv run sentinel validate orders
```

`orders` resolves to two files:

```yaml
# datasets/orders.yaml: where the data is and how important it is
id: orders
name: orders
source_type: duckdb
environment: local
owner: data-platform-team
criticality: high
config_reference: data/orders.csv
```

```yaml
# policies/orders.yaml: what "good" means (excerpt)
dataset: orders
rules:
  - name: customer_id_not_null
    type: null_rate
    column: customer_id
    threshold:
      strategy: static
      max: 0.01
  - name: unique_order_id
    type: uniqueness
    column: order_id
    threshold:
      strategy: static
      max: 0
```

The bundled sample deliberately contains problems: too few rows, a null `customer_id`, a duplicated order, and a stale timestamp. Illustrative output (abridged):

```text
Dataset: orders
Run ID:  6f0c2a8e-1d3b-4e5f-9a7c-2b8d4e6f1a3c
Result:  FAIL (blocking)

  ✗ row_count  actual=12  expected: row_count >= 1000
      priority=WARNING score=49.9  Dataset criticality: HIGH
  ✗ customer_id_not_null  actual=0.08333  expected: customer_id_not_null <= 0.01
      priority=HIGH score=60.0  Dataset criticality: HIGH
  ✗ unique_order_id  actual=1  expected: unique_order_id <= 0
      priority=HIGH score=60.0  Dataset criticality: HIGH
  ...
```

Then look at the history and the dashboard:

```bash
uv run sentinel history orders

uv sync --group dashboard
uv run streamlit run dashboard/app.py
```

### Explore every feature

Four more example datasets sit next to `orders`: a clean one, one with a non-blocking failure, one comparing all four adaptive threshold strategies, and a Postgres table. Prepare them once, then validate each:

```bash
uv run python -m examples.setup     # backfills history + loads the Postgres example
uv run sentinel validate signups    # customers, products, orders, signups, events
```

The [guided tour](docs/examples.md) explains what each one shows, the expected result, and things to try.

### Guided demo

`demo/run_demo.sh` replays four daily loads of a critical `payments` dataset (a clean load, a bad load, the problem persisting, then a partial fix) into an isolated store. It then shows the run history:

```bash
bash demo/run_demo.sh              # four validations + history
bash demo/run_demo.sh dashboard    # open the dashboard on the demo store
```

It uses its own `demo/` datasets, policies and database and touches nothing else.

---

## Using Sentinel in a pipeline

Add a validation step after each load and before anything downstream reads the data:

```bash
sentinel validate orders || exit $?
```

| Exit code | Meaning |
|---|---|
| `0` | No blocking rule failed. Non-blocking failures are still printed and recorded. |
| `1` | A rule warned. Also returned for execution errors such as a malformed policy or an unreachable database, together with a traceback. |
| `2` | A rule with `blocking: true` (the default) failed |

Treat any non-zero code as "do not continue". Every completed run is persisted whatever its outcome, so `history` and the dashboard show non-blocking failures too.

## Writing policies

```yaml
- name: daily_orders              # stable name: it is also the history key
  type: row_count                 # row_count | null_rate | uniqueness | freshness | schema
  severity: high                  # info | warning (default) | high | critical
  blocking: true                  # default true
  threshold:
    strategy: seasonal            # static | percentage_deviation | statistical | median_mad | seasonal
    n_sigma: 3
    min_history: 2
```

- [Configuration reference](docs/components/configuration.md): every field of the dataset and policy files
- [Rules](docs/components/rules.md): what each rule measures
- [Threshold strategies](docs/components/thresholds.md): parameters, and when to use each strategy

---

## Architecture

Sentinel is a single Python package with strict, inward-pointing dependencies:

- **`domain/`:** plain data, no dependencies. *Definitions* (Policy, RuleConfig, ThresholdConfig, Dataset) are kept separate from immutable *facts* (Metric, ThresholdResult, QualityEvent, ValidationRun, Incident).
- **`rules/`, `thresholds/`, `datasources/`:** pluggable `Protocol` interfaces, each with a decorator-based registry keyed by the string used in YAML.
- **`orchestration/`, `prioritization/`:** pure coordination logic. History arrives through injected interfaces, so the core runs and is tested without any database.
- **`persistence/`, `observability/`, `validation_service.py`:** the Postgres store (migrations, per-dataset run locking, history reads) and the read-only query layer.
- **`cli/`, `dashboard/`:** the edges. `cli/main.py` is the one place where concrete implementations are wired together.

Read more:

- [Architecture Overview](docs/architecture/overview.md): layers, dependency rules, execution sequence, patterns
- [Design Decisions](docs/architecture/design-decisions.md): what was decided, what was rejected, and when to revisit
- [Interactive architecture diagram](docs/assets/architecture.html) (open it locally in a browser)
- [Full documentation index](docs/README.md)

## Project layout

```text
src/sentinel/
  domain/           Definitions and runtime facts (pydantic + frozen dataclasses)
  config_loading.py Shared YAML -> validated model loader
  policy_loader/    Policy YAML loader
  dataset_loader/   Dataset YAML loader
  rules/            Rule protocol, registry, 5 rules
  datasources/      DataSource protocol, registry, shared SQL base, six adapters
  thresholds/       ThresholdStrategy protocol, registry, 5 strategies, history interface
  orchestration/    ValidationOrchestrator
  prioritization/   IncidentPrioritizer and scoring model
  persistence/      Postgres connections, Alembic migrations, run lock, writer, history readers
  observability/    Read-only query service and read models
  validation_service.py  Lock, run, persist: the one path for recording a validation
  cli/              `sentinel validate`, `sentinel history`, `sentinel db`
  registration.py   Registers every built-in plug-in
dashboard/app.py    Streamlit dashboard
datasets/ policies/ data/   Example datasets, policies and sample data (docs/examples.md)
examples/           Setup for the examples (history backfill, Postgres table)
demo/               Self-contained guided demo
experiments/        Reproducible threshold-strategy evaluation
tests/unit/         Mirrors src/sentinel/
tests/integration/  CLI, end-to-end, concurrent runs, adapter contract, examples, observability
docs/               Architecture, component reference, experiment results
```

---

## Development

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
```

CI (`.github/workflows/ci.yml`) runs lint, strict type checking and the full test suite against a real Postgres service on every push and pull request.

### Postgres

The store tests and the Postgres adapter tests need a running database. They create and use a separate `sentinel_test` database, and skip when no server is reachable (CI makes them fail instead).

```bash
docker compose up -d
uv run pytest
```

Schema changes are Alembic migrations in `src/sentinel/persistence/migrations/versions/`. Create one with `uv run alembic revision -m "..."` and apply with `uv run sentinel db upgrade`.

`docker compose up -d` also starts MySQL and MongoDB for the adapter contract tests. Snowflake and BigQuery contract tests run when `SENTINEL_TEST_SNOWFLAKE_URL` / `SENTINEL_TEST_BIGQUERY_URL` are set. To validate other sources, see [Data Sources](docs/components/data-sources.md#configuration-per-source); install their drivers with `uv sync --extra snowflake` (or `mysql`, `bigquery`, `mongodb`, `all-sources`).

### Docker

```bash
docker build -t sentinel .
docker run --rm --network host sentinel   # runs the test suite; needs `docker compose up -d` for the store tests
```

### Regenerating the threshold evaluation

```bash
uv run python -m experiments.threshold_intelligence.runner
```

This rewrites [`docs/experiments/threshold-strategy-evaluation.md`](docs/experiments/threshold-strategy-evaluation.md). The output is seeded and deterministic, and `tests/unit/experiments/test_runner.py` pins its conclusions.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SENTINEL_DATABASE_URL` | `postgresql://sentinel:sentinel@localhost:5432/sentinel` | Sentinel's Postgres store |
| `SENTINEL_DATASETS_DIR` | `datasets` | Dataset YAML directory |
| `SENTINEL_POLICIES_DIR` | `policies` | Policy YAML directory |
| `SENTINEL_TEST_POSTGRES_DSN` | compose Postgres | Server used by the tests (they create `sentinel_test`) |

---

## Known limitations

- **Adaptive thresholds need a warm-up.** A new rule configured directly with an adaptive strategy fails the run with `InsufficientHistoryError` until it has history. Start the rule on `static` and switch once enough runs exist; history is keyed by rule name, so it carries over. See [Thresholds: cold start](docs/components/thresholds.md#cold-start).
- **Runs of the same dataset queue up.** Simultaneous runs of one dataset are serialized so each sees the previous run's history; different datasets run in parallel.
- **No per-team isolation.** All teams share one store; a dataset's `owner` records its team, but nothing restricts who can read or write it.
- **No HTTP API yet.** Validation runs from the CLI; the store and run locking are ready for an API layer.
- **Execution errors abort the whole run.** If one rule cannot execute, nothing from that run is persisted.
- **No built-in WARN.** The built-in strategies return PASS or FAIL only.
- **Policies are versioned by hand** through the optional `version:` field.
- **Renaming a rule resets its history.**
- **One dataset is one table or collection.** Joins and custom SQL aren't supported; point the dataset at a view instead.

## License

MIT. See [LICENSE](LICENSE).
