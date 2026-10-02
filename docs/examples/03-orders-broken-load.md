# 3. A broken load: `orders`

**The situation.** The orders pipeline normally lands thousands of rows a day. Today's file is a mess: a tiny partial extract, a missing customer, a duplicated order, and timestamps weeks old. This is the load Sentinel exists to stop before it reaches a dashboard or a finance report.

**You'll learn:** all five rule types failing at once, exit code `2`, how priorities differ between failures, and what changes when the same failure keeps happening.

```bash
uv run sentinel validate orders
```

---

## The data

`data/orders.csv` has 12 rows, with four problems planted in them:

```text
order_id,customer_id,order_total,updated_at
1001,C001,59.99,2026-08-23T10:00:00Z
1004,,75.25,2026-08-23T07:15:00Z          ← no customer
1007,C006,45.00,2026-08-20T12:00:00Z
1007,C006,45.00,2026-08-20T12:00:00Z      ← the same order twice
1010,C009,5.00,2026-06-01T00:00:00Z       ← months old
...
```

The whole file is also far too small, and its newest timestamp (23 August) is long past.

## The policy

`datasets/orders.yaml` marks the dataset `criticality: high`. Every rule is blocking and uses the default severity (`warning`):

| Rule | Type | Threshold | Catches |
|---|---|---|---|
| `row_count` | `row_count` | `min: 1000` | A partial extract |
| `customer_id_not_null` | `null_rate` on `customer_id` | `max: 0.01` (1%) | Orders that can't be attributed |
| `unique_order_id` | `uniqueness` on `order_id` | `max: 0` | Duplicated orders (double-counted revenue) |
| `orders_freshness` | `freshness` on `updated_at` | `max: 60` (minutes) | A stale or stuck feed |
| `orders_schema` | `schema` | `max: 0` | A changed file layout or column type |

## What you'll see

```text
Dataset: orders
Run ID:  07a8a0e3-1518-4e20-8ca7-75b026557351
Result:  FAIL (blocking)

  ✗ row_count  actual=12  expected: row_count >= 1000
      priority=WARNING score=49.9  Dataset criticality: HIGH
  ✗ customer_id_not_null  actual=0.08333  expected: customer_id_not_null <= 0.01
      priority=HIGH score=60.0  Dataset criticality: HIGH
  ✗ unique_order_id  actual=1  expected: unique_order_id <= 0
      priority=HIGH score=60.0  Dataset criticality: HIGH
  ✗ orders_freshness  actual=5.808e+04  expected: orders_freshness <= 60
      priority=HIGH score=60.0  Dataset criticality: HIGH
  ✗ orders_schema  actual=1  expected: orders_schema <= 0
      priority=HIGH score=60.0  Dataset criticality: HIGH
```

Exit code `2`: a scheduler such as Airflow or cron would stop here. Reading each line:

- **`row_count`**: 12 rows against a minimum of 1000.
- **`customer_id_not_null`**: 1 of 12 rows (8.3%) has no customer, against a 1% limit.
- **`unique_order_id`**: one duplicated value. Uniqueness counts *extra* copies, so two rows with order 1007 count as 1.
- **`orders_freshness`**: the newest `updated_at` is about 58,000 minutes (40 days) old. This number grows every day you run it.
- **`orders_schema`**: one difference. DuckDB reads a CSV value like `59.99` as a floating-point number, so `order_total` comes back as `float`, not the `decimal` the policy expects. This is the kind of silent type drift the schema rule exists to catch. If your copy passes this rule, your file was read with different types; the rest of the output is the same.

**Why is the 12-row load only WARNING?** Deviation earns full points only when the value misses its limit by twice the limit itself. The other four failures do (8.3% against 1%, for example). For `row_count`, the shortfall is 988 against a floor of 1000, a ratio of about 1, so deviation earns about half its points and the incident scores 49.9, just under the HIGH cut-off of 50. See [scenario 2](02-products-non-blocking-rules.md#why-warning-if-severity-is-info-and-criticality-is-low) for how scores add up.

**Why can't anything here reach CRITICAL?** With the default severity (`warning`) and a `high` dataset, the highest possible score is 73. To let a rule escalate to CRITICAL, give it `severity: critical` (scenario 6 does) or mark the dataset `criticality: critical`.

## The same failure, again and again

Run it four more times, then look at the history:

```bash
for i in 1 2 3 4; do uv run sentinel validate orders > /dev/null; done
uv run sentinel validate orders | grep -A1 customer_id_not_null
uv run sentinel history orders --limit 5
```

```text
  ✗ customer_id_not_null  actual=0.08333  expected: customer_id_not_null <= 0.01
      priority=HIGH score=69.7  Dataset criticality: HIGH
```

```text
Dataset: orders

  2026-10-02T17:56:48+00:00  FAIL  run=b0bd9c23-…  failed: customer_id_not_null, orders_freshness, row_count, unique_order_id
  2026-10-02T17:56:48+00:00  FAIL  run=cab62640-…  failed: customer_id_not_null, orders_freshness, row_count, unique_order_id
  ...
```

The score rose from 60.0 to 69.7. Sentinel looks at each rule's last 90 results: a rule that fails every time scores the maximum on frequency, and consecutive failures raise its confidence that the problem is real. A one-off glitch and a problem that has persisted for a week get different priorities, even with identical values.

In the dashboard (scenario 10), these rules move from *first occurrence* to *persistent* under Recurring Failures.

## Try it

- **Fix the data one problem at a time** (keep a copy: `cp data/orders.csv /tmp/orders.csv`). Fill in the blank `customer_id` and delete the duplicate line, then rerun: those two rules pass, the rest still fail.
- **Accept DuckDB's type:** change `order_total: decimal` to `float` in `policies/orders.yaml`. The schema rule passes.
- **Make the freshness rule pass:** set every `updated_at` to a time within the last hour (UTC).

Restore with `git checkout data/orders.csv policies/orders.yaml`.

**Next:** [4. Thresholds that learn](04-signups-adaptive-thresholds.md)
