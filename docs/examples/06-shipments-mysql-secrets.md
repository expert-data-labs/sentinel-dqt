# 6. MySQL and secrets: `shipments`

**The situation.** The logistics team's shipments live in MySQL. Each order should ship exactly once; a second shipment means a customer is charged twice or a parcel goes out twice. Today two orders were shipped twice. And because this config is committed to Git, the database password must not be in it.

**You'll learn:** how to keep credentials out of configuration, how a severe failure becomes a CRITICAL incident, and how MySQL's types map onto the schema rule.

```bash
export MYSQL_PASSWORD=sentinel      # the Docker default
uv run sentinel validate shipments
```

> `examples.setup` loads 300 shipments into MySQL. Orders 17 and 42 appear twice, and about 2% of shipments have no carrier.

---

## Secrets from the environment

`datasets/shipments.yaml`:

```yaml
id: shipments
source_type: mysql
owner: logistics-team
criticality: high
config_reference: mysql://sentinel:${MYSQL_PASSWORD}@localhost:3306/sentinel?table=shipments
```

`${MYSQL_PASSWORD}` is replaced with the environment variable of that name when the run starts. The YAML file, and the copy of the dataset Sentinel stores with each run, only ever contain `${MYSQL_PASSWORD}`, never the password. In production, your scheduler or CI injects the variable from its secret store.

If the variable isn't set, the run stops before connecting and names what's missing:

```text
ConfigReferenceError: config_reference uses unset environment variable(s): MYSQL_PASSWORD
```

This works the same for every source: `${PG_PASSWORD}`, `${SNOWFLAKE_PASSWORD}`, `${MONGO_PASSWORD}`, any name you like. BigQuery and S3 need no secret in the config at all; they use their platform's own credentials.

## The policy

| Rule | Type | Severity | Threshold |
|---|---|---|---|
| `row_count` | `row_count` | warning (default) | at least 100 |
| `one_shipment_per_order` | `uniqueness` on `order_id` | **critical** | no duplicates |
| `carrier_not_null` | `null_rate` on `carrier` | high | at most 5% |
| `shipments_freshness` | `freshness` on `shipped_at` | warning (default) | at most 120 minutes |
| `shipments_schema` | `schema` | warning (default) | includes `weight_kg: decimal`, `insured: boolean` |

## What you'll see

```text
Dataset: shipments
Run ID:  4ac8a899-9bc5-441d-a10c-6880c343a790
Result:  FAIL (blocking)

  ✓ row_count  actual=300  expected: row_count >= 100
  ✗ one_shipment_per_order  actual=2  expected: one_shipment_per_order <= 0
      priority=CRITICAL score=78.0  Dataset criticality: HIGH
  ✓ carrier_not_null  actual=0.02  expected: carrier_not_null <= 0.05
  ✓ shipments_freshness  actual=0.02542  expected: shipments_freshness <= 120
  ✓ shipments_schema  actual=0  expected: shipments_schema <= 0
```

Exit code `2`.

- **`one_shipment_per_order`**: `actual=2`, one extra row for each of orders 17 and 42.
- **CRITICAL, score 78.0**: severity critical (30 points) + criticality high (21) + a maximal deviation (20) + first occurrence (1) + confidence (6). This is the first example to cross the CRITICAL line of 75, because the rule itself is marked `critical`. Compare `orders` in scenario 3, where the same kind of failure with the default severity scored 60 (HIGH).
- **`carrier_not_null`**: 2% missing carriers is within the 5% allowance, so it passes. Not every gap is a failure; the threshold encodes what the business tolerates.
- **`shipments_schema`**: `insured` is a MySQL `BOOLEAN`, which MySQL actually stores as `tinyint(1)`. Sentinel reports it as `boolean`, so the expected schema reads the way you think about the data, not the way MySQL stores it. `DECIMAL(6,2)` is `decimal`, and `DATETIME` is `timestamp` (treated as UTC).

In the dashboard, `shipments` shows **critical** health, because its latest run has a CRITICAL incident.

## Try it

- **Run without the secret:** `unset MYSQL_PASSWORD` and rerun to see the error above. Nothing is read or recorded.
- **Remove the duplicates:**
  ```bash
  docker compose exec mysql mysql -usentinel -psentinel sentinel \
    -e "DELETE FROM shipments WHERE shipment_id > 298"
  ```
  The two extra shipments were the last rows loaded, so this deletes exactly them. Every rule passes and exit code is `0`. `uv run python -m examples.setup` restores the original table.

**Next:** [7. Documents in MongoDB](07-reviews-mongodb.md)
