# 12. Validate your own data

**The situation.** You've seen what Sentinel does. Now you want it watching one of your own tables.

This page walks through it in five steps, using a hypothetical `payments` table in Postgres. Swap in your own source, names and columns.

---

## Step 1. Describe the dataset

Create `datasets/payments.yaml`. The file name is what you'll type in `sentinel validate payments`.

```yaml
id: payments                     # stable key for all history; keep id and name the same
name: payments
source_type: postgres
environment: prod
owner: payments-team             # who gets asked when it breaks
criticality: critical            # low | medium | high | critical
config_reference: postgresql://reader:${PAYMENTS_DB_PASSWORD}@db.internal:5432/finance?table=public.payments&sslmode=require
```

`config_reference` for each source:

| `source_type` | `config_reference` | Extra to install |
|---|---|---|
| `duckdb` | `data/file.csv`, `data/*.parquet`, `s3://bucket/path/*.parquet`, `data/file.jsonl` | none |
| `postgres` | `postgresql://user:${PW}@host:5432/db?table=schema.table` | none |
| `mysql` | `mysql://user:${PW}@host:3306/db?table=table` | `uv sync --extra mysql` |
| `mongodb` | `mongodb://user:${PW}@host:27017/db?collection=name` | `uv sync --extra mongodb` |
| `snowflake` | `snowflake://user:${PW}@account/DATABASE/SCHEMA?warehouse=WH&table=name` | `uv sync --extra snowflake` |
| `bigquery` | `bigquery://project/dataset?table=name` (uses Google default credentials) | `uv sync --extra bigquery` |

`--extra all-sources` installs every driver. More options per source: [Data Sources](../components/data-sources.md#configuration-per-source).

**Use a read-only database user.** Sentinel only runs `SELECT`s against your data.

## Step 2. Start with static rules

Create `policies/payments.yaml`. Begin with what you know must always be true; these are hard business rules, so `static` thresholds suit them.

```yaml
dataset: payments
version: "1"
rules:
  - name: daily_volume
    type: row_count
    threshold:
      strategy: static
      min: 1                     # generous for now; step 4 makes it smarter

  - name: payment_id_unique
    type: uniqueness
    column: payment_id
    severity: critical
    threshold: {strategy: static, max: 0}

  - name: amount_present
    type: null_rate
    column: amount
    severity: high
    threshold: {strategy: static, max: 0}

  - name: payments_fresh
    type: freshness
    column: created_at
    threshold: {strategy: static, max: 90}      # minutes

  - name: payments_schema
    type: schema
    expected_schema:
      payment_id: string
      amount: decimal
      currency: string
      created_at: timestamp
    threshold: {strategy: static, max: 0}
```

**Choosing the rules:**

| If you worry about… | Use | Typical threshold |
|---|---|---|
| A partial or empty load | `row_count` | `min`, later an adaptive strategy |
| Missing values in a key column | `null_rate` | `max: 0` for keys, a small fraction for optional fields |
| Duplicates | `uniqueness` | `max: 0` |
| A stuck or late feed | `freshness` | `max` in minutes, a bit above your load interval |
| Upstream schema changes | `schema` | `max: 0` |

**Choosing blocking and severity:** keep a rule blocking (the default) if bad data must not go further. Use `blocking: false` for rules you're still trialling or only want to track (scenario 2). Set `severity` to how bad a failure of that rule is. It feeds the incident's priority, not the exit code.

**Writing `expected_schema`:** list every column, with its type translated from your table definition through the [canonical type table](../components/data-sources.md#canonical-column-types) (`bigint` → `integer`, `numeric` → `decimal`, `timestamptz` → `timestamp`, and so on). Missing, extra and retyped columns each count as one difference. For CSV files the types are whatever DuckDB infers, so expect to adjust after the first run (scenario 3).

## Step 3. Run it

```bash
export PAYMENTS_DB_PASSWORD=...
uv run sentinel validate payments
echo $?          # 0 pass, 2 blocking failure, 3 store not set up
```

Keep your own configs outside this repository by pointing Sentinel at their folders:

```bash
export SENTINEL_DATASETS_DIR=/etc/sentinel/datasets
export SENTINEL_POLICIES_DIR=/etc/sentinel/policies
```

## Step 4. Make volume adaptive, once there's history

After a week or two of daily runs (enough for `min_history`), switch `daily_volume` to a learning strategy. **Keep the rule's name** so it keeps its history:

```yaml
  - name: daily_volume           # same name: history carries over
    type: row_count
    blocking: false              # shadow it for a while first
    threshold:
      strategy: seasonal         # weekly pattern? seasonal. Steady level? median_mad
      n_sigma: 3
      min_history: 2             # per weekday
```

Scenario 4 explains the strategies, and you can test a policy against eight simulated weeks before trusting it (scenario 9). When its verdicts look right, remove `blocking: false` and bump `version`.

## Step 5. Put it in the pipeline

Run the check after each load and let the exit code decide:

```bash
# e.g. a step in cron, CI or an Airflow BashOperator
uv run sentinel validate payments || exit $?     # 2 stops the pipeline
```

Every run lands in the store, so the dashboard (scenario 10) shows the dataset's health, incidents and trends with no extra work.

---

**Reference:** [Configuration](../components/configuration.md) · [Rules](../components/rules.md) · [Threshold strategies](../components/thresholds.md) · [Prioritization](../components/prioritization.md) · [CLI](../components/cli.md)

**Back to:** [all scenarios](README.md)
