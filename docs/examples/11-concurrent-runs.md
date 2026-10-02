# 11. Many pipelines at once

**The situation.** Sentinel isn't run by one person on a laptop. Several teams' pipelines call `sentinel validate` from their schedulers at the same time, all writing to one shared store. And sometimes the same dataset is validated twice at once: a retry overlaps the original, or two DAGs both check a shared table. You need the results to stay correct.

**You'll learn:** what Sentinel guarantees when runs overlap, and why runs of the same dataset wait for each other.

---

## Different datasets run in parallel

```bash
for d in customers products orders signups events shipments reviews clickstream; do
  uv run sentinel validate $d &
done
wait
```

All eight run at the same time and none waits for another. Each run is saved in a single transaction, so the dashboard and `sentinel history` never show a half-written run, even while they're being written.

## The same dataset runs one at a time

Run one dataset twice, simultaneously, on a fresh history:

```bash
uv run sentinel validate products & uv run sentinel validate products & wait
```

```text
      priority=WARNING score=33.0  Dataset criticality: LOW      ← one run
      priority=WARNING score=42.2  Dataset criticality: LOW      ← the other
```

```text
$ uv run sentinel history products
  2026-10-02T18:02:25+00:00  FAIL  run=479d48f8-…  failed: description_not_null
  2026-10-02T18:02:25+00:00  FAIL  run=89134621-…  failed: description_not_null
```

(These scores are from a store where `products` had no earlier runs. With your history from scenario 2 both scores will be higher, but the second is still higher than the first.)

Both runs are recorded, but they score differently, and that's the point. The second run waited for the first to finish, then read its result: it saw that `description_not_null` had already failed once, so it scored it as a repeated failure (42.2), not a first one (33.0).

**Why this matters.** Every run *reads* history (adaptive thresholds need past values, priority needs past failures), then *writes* its own result. If two runs of one dataset overlapped freely, both would read the same history and neither would see the other. An adaptive baseline would silently skip a data point, and a failure happening twice would be scored as new both times. So Sentinel holds a per-dataset lock in Postgres from the read to the write. It is keyed by the dataset, so other datasets are never held up, and Postgres releases it automatically if a process crashes.

## In production

- **Point every process at the same store** with `SENTINEL_DATABASE_URL`. Pipelines, the dashboard and future API workers can all share it.
- **Schema changes are migrations**, applied once per deployment with `sentinel db upgrade`. A run against a store that hasn't been upgraded stops with exit code `3` (see [scenario 10](10-history-and-dashboard.md#try-it)).
- **Every dataset records its `owner`**, so one shared store can serve many teams.

Details: [Persistence: concurrency](../components/persistence.md#concurrency). The guarantees are tested by `tests/integration/test_concurrent_runs.py`.

**Next:** [12. Validate your own data](12-your-own-dataset.md)
