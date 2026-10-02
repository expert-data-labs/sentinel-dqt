# 5. Checking a Postgres table: `events`

**The situation.** Product events land in a Postgres table every few minutes. Analysts expect the table to be current to within the hour, every event to have a unique id, and only a small share of anonymous (no `user_id`) events. You want the same kind of checks you ran on CSV files, pointed at a live table.

**You'll learn:** how database sources are configured, how Sentinel measures without copying your data, and how database types map to the schema rule's types.

```bash
uv run sentinel validate events
```

> `examples.setup` creates a `sentinel_examples` database on the Docker Postgres and loads 500 events from the last 30 minutes into an `events` table. 1% of the events have no `user_id`.

---

## The dataset file

```yaml
id: events
name: events
source_type: postgres
owner: data-platform-team
criticality: high
config_reference: postgresql://sentinel:sentinel@localhost:5432/sentinel_examples?table=events
```

For databases, `config_reference` is a connection URL plus a `table` parameter. `table` can include a schema (`?table=analytics.events`), and any other parameter, such as `sslmode=require`, is passed on to the driver.

The password is in plain text here only because this is the local Docker default. For anything real, use `${PG_PASSWORD}` (scenario 6).

## How Sentinel reads the table

Sentinel never pulls the table into memory. Each rule is answered by one or two small aggregate queries that run inside the database: `COUNT(*)`, `COUNT(*) … WHERE user_id IS NULL`, `COUNT(DISTINCT event_id)`, `MAX(occurred_at)`, and a lookup of the column types in `information_schema`. Only the resulting numbers travel back, so checking a billion-row table costs a few aggregate queries, not a transfer.

## The policy

| Rule | Type | Threshold |
|---|---|---|
| `row_count` | `row_count` | at least 100 rows |
| `user_id_null_rate` | `null_rate` on `user_id` | at most 2% anonymous |
| `event_id_unique` | `uniqueness` on `event_id` | no duplicates |
| `events_freshness` | `freshness` on `occurred_at` | newest event at most 60 minutes old |
| `events_schema` | `schema` | `event_id: integer`, `user_id: string`, `event_type: string`, `occurred_at: timestamp` |

These are the same rule types as in scenarios 1–3. Rules don't know where data comes from: switching from a CSV file to a warehouse table changes the dataset file, not the policy.

## What you'll see

```text
Dataset: events
Run ID:  2cce531a-5221-477d-b1d5-bd681f3595d9
Result:  PASS

  ✓ row_count  actual=500  expected: row_count >= 100
  ✓ user_id_null_rate  actual=0.01  expected: user_id_null_rate <= 0.02
  ✓ event_id_unique  actual=0  expected: event_id_unique <= 0
  ✓ events_freshness  actual=0.03184  expected: events_freshness <= 60
  ✓ events_schema  actual=0  expected: events_schema <= 0
```

- **Freshness** is in minutes: the newest event is seconds old. Timestamps are compared in UTC, whatever time zone the column or the server uses.
- **Schema** passes because each Postgres type maps to a canonical one: `bigint` → `integer`, `text` → `string`, `timestamptz` → `timestamp`. The full mapping for every source is in [Canonical column types](../components/data-sources.md#canonical-column-types).

## Try it

- **Let it go stale.** Come back after an hour and rerun: `events_freshness` fails. `uv run python -m examples.setup` reloads fresh events.
- **Add anonymous events.** Push the null rate past 2%:
  ```bash
  docker compose exec postgres psql -U sentinel -d sentinel_examples \
    -c "UPDATE events SET user_id = NULL WHERE event_id <= 20"
  ```
  `user_id_null_rate` fails (about 0.05 against 0.02; the exact value depends on how many of those 20 were already anonymous).
- **Change a column type.** `ALTER TABLE events ALTER COLUMN event_id TYPE text` makes `events_schema` fail with one type mismatch.

**Next:** [6. MySQL and secrets](06-shipments-mysql-secrets.md)
