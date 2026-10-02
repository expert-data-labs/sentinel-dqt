# 8. Parquet files and data lakes: `clickstream`

**The situation.** The web team exports clickstream events as Parquet files, the usual format for a data lake. Today it's one local file; in production it would be a folder of files in S3. You want to check them in place, without loading them into a database first.

**You'll learn:** checking Parquet (and JSON) files, pointing one dataset at many files, reading straight from S3, and why Parquet makes the schema check exact.

```bash
uv run sentinel validate clickstream
```

> `examples.setup` writes 5000 page events to `data/generated/clickstream.parquet` (that folder is ignored by Git).

---

## The dataset file

```yaml
id: clickstream
source_type: duckdb
owner: analytics-team
criticality: medium
config_reference: data/generated/clickstream.parquet
```

The same `duckdb` source type reads CSV, Parquet and JSON. It picks the reader from the file extension, and `config_reference` can be any of:

```yaml
config_reference: data/generated/clickstream.parquet       # one file
config_reference: data/clickstream/*.parquet               # every matching file, read as one dataset
config_reference: s3://lake/clickstream/2026/10/*.parquet  # straight from S3
config_reference: data/events.jsonl                        # JSON / newline-delimited JSON
```

DuckDB queries the files where they are. For S3 it uses your standard AWS credentials (environment variables, `~/.aws`, or the machine's role), so no secret goes in the YAML.

## The policy

| Rule | Type | Threshold |
|---|---|---|
| `row_count` | `row_count` | at least 1000 |
| `event_id_unique` | `uniqueness` on `event_id` | no duplicates |
| `session_id_not_null` | `null_rate` on `session_id` | no missing sessions |
| `clickstream_schema` | `schema` | `event_id: integer`, `session_id: string`, `page: string`, `duration_ms: integer`, `occurred_at: timestamp` |

## What you'll see

```text
Dataset: clickstream
Run ID:  fb6cb306-ef21-46c3-8237-1204a5c1ed7c
Result:  PASS

  ✓ row_count  actual=5000  expected: row_count >= 1000
  ✓ event_id_unique  actual=0  expected: event_id_unique <= 0
  ✓ session_id_not_null  actual=0  expected: session_id_not_null <= 0
  ✓ clickstream_schema  actual=0  expected: clickstream_schema <= 0
```

**Why the schema check is exact here.** A CSV file is just text, so DuckDB has to *guess* each column's type, which is why `order_total` came back as `float` in scenario 3. A Parquet file stores each column's real type, so the schema rule checks what the producer actually wrote. If an upstream job starts writing `duration_ms` as a string, this rule catches it on the first file.

## Try it

- **Validate a folder of files.** Copy the file twice and point the dataset at all of them:
  ```bash
  mkdir -p data/generated/days
  cp data/generated/clickstream.parquet data/generated/days/day1.parquet
  cp data/generated/clickstream.parquet data/generated/days/day2.parquet
  ```
  Set `config_reference: data/generated/days/*.parquet` and rerun. `row_count` is now 10000, and `event_id_unique` fails with `actual=5000`: every id appears twice. This is exactly what happens when a job writes the same partition twice.
- **Use your own bucket.** With AWS credentials in your environment, set `config_reference` to an `s3://` path to one of your Parquet folders, and adjust the policy's rules and columns to match.

Restore with `git checkout datasets/clickstream.yaml`.

**Next:** [9. Replay eight weeks](09-simulator-adaptive-thresholds.md)
