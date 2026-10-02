# 1. A healthy dataset: `customers`

**The situation.** The CRM team publishes a customer list every day. Downstream jobs join on `customer_id` and email customers, so a missing email or a duplicated id would cause real damage. You want Sentinel to confirm, on every load, that neither has happened.

**You'll learn:** the shape of a dataset and a policy, four of the five rule types, how the schema check works, and what a passing run looks like.

```bash
uv run sentinel validate customers
```

---

## The data

`data/customers.csv`: 50 customers, every field filled in, no duplicates.

```text
customer_id,email,country,signup_date
1,customer001@example.com,US,2026-03-24
2,customer002@example.com,BR,2026-04-12
```

## The dataset file

`datasets/customers.yaml` says *what* to check:

```yaml
id: customers
name: customers
source_type: duckdb              # DuckDB reads CSV, Parquet and JSON files
environment: local
owner: crm-team
criticality: medium              # how much this dataset matters: low | medium | high | critical
config_reference: data/customers.csv
```

`config_reference` means something different for each `source_type`. For files it is a path; for databases it is a connection URL (see scenario 5).

## The policy

`policies/customers.yaml` says *how* to check it (thresholds condensed onto one line here):

```yaml
dataset: customers
version: "2026-10-01"            # optional; stored with every run
rules:
  - name: row_count
    type: row_count
    threshold: {strategy: static, min: 10}

  - name: email_not_null
    type: null_rate
    column: email
    severity: high
    threshold: {strategy: static, max: 0}       # no missing emails at all

  - name: customer_id_unique
    type: uniqueness
    column: customer_id
    severity: critical
    threshold: {strategy: static, max: 0}       # no duplicate ids

  - name: customers_schema
    type: schema
    expected_schema:
      customer_id: integer
      email: string
      country: string
      signup_date: date
    threshold: {strategy: static, max: 0}       # no column differences
```

| Rule | Measures | Passes when |
|---|---|---|
| `row_count` | Number of rows | At least 10 |
| `email_not_null` | Fraction of rows with no email | Exactly 0 |
| `customer_id_unique` | Number of duplicate ids | Exactly 0 |
| `customers_schema` | Missing, extra or retyped columns | Exactly 0 |

A few things worth knowing:

- **`name` is the rule's identity.** History, trends and incident frequency are all keyed by it. You can change a rule's threshold freely, but renaming it starts its history from scratch.
- **`severity`** (info, warning, high, critical; default warning) says how serious *this rule's* failure is. Together with the dataset's `criticality` it drives incident priority (scenario 2).
- **Rules are blocking by default:** any failure stops the pipeline with exit code `2`.
- **The schema check compares canonical types:** `integer`, `float`, `decimal`, `string`, `boolean`, `date`, `timestamp`. Every adapter maps its native types to these, so the same `expected_schema` works on a CSV file, a Postgres table or a MongoDB collection.
- **`version`** is optional. When you change a policy, bump it, and every run records which version judged it.

## What you'll see

```text
Dataset: customers
Run ID:  54bedcbb-b797-44ad-b8a7-254c287e22dd
Result:  PASS

  ✓ row_count  actual=50  expected: row_count >= 10
  ✓ email_not_null  actual=0  expected: email_not_null <= 0
  ✓ customer_id_unique  actual=0  expected: customer_id_unique <= 0
  ✓ customers_schema  actual=0  expected: customers_schema <= 0
```

Exit code `0`. All four rules pass, no incidents are created, and the run is stored. Every run is stored, passing or not, because a passing run is history too: scenario 4 shows adaptive thresholds learning from exactly these numbers.

## Try it

Make a copy first: `cp data/customers.csv /tmp/customers.csv`.

| Change in `data/customers.csv` | What happens |
|---|---|
| Blank one email | `email_not_null` fails (`actual=0.02`); exit `2` |
| Duplicate any line | `customer_id_unique` fails (`actual=1`) and `row_count` becomes 51; exit `2` |
| Rename the `country` header to `region` | `customers_schema` fails with `actual=2`: one missing column and one unexpected column |
| Delete all but 5 rows | `row_count` fails; exit `2` |

Restore with `cp /tmp/customers.csv data/customers.csv` (or `git checkout data/customers.csv`).

**Next:** [2. Track a problem without blocking](02-products-non-blocking-rules.md)
