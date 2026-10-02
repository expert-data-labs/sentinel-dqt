# 10. History and the dashboard

**The situation.** It's Monday morning. You want to know which datasets are in trouble, what broke over the weekend, whether it's new or has been failing for days, and whether a metric is drifting. Every run from scenarios 1–9 is already stored, so the answers are a query away.

**You'll learn:** `sentinel history`, every view in the dashboard, and how Sentinel decides a dataset's health and whether a failure is recurring.

---

## Run history from the command line

```bash
uv run sentinel history signups --limit 4
```

```text
Dataset: signups

  2026-10-02T17:56:25+00:00  FAIL  run=fe8b216e-f298-479b-b9b0-133f0ee89aae  failed: row_count_vs_recent_mean
  2026-10-01T17:56:24+00:00  PASS  run=341185dd-6a8e-4255-b7c3-6b2b76822489
  2026-09-30T17:56:24+00:00  PASS  run=304879b3-c4c4-4fa2-bd35-5aa1f1a16fa2
  2026-09-29T17:56:24+00:00  PASS  run=dfdb1172-3cbc-4fca-9ac2-a18787dcfc23
```

One line per run, newest first, with the rules that failed. The status reports *every* failure, including non-blocking ones, so today's signups run is `FAIL` here even though its exit code was `0`. History answers "what went wrong"; the exit code answers "should the pipeline stop".

To see one run in full (every rule, the threshold details, and each incident's score parts and reasons), pass its Run ID to `uv run python demo/inspect_run.py <run-id>` (see [scenario 2](02-products-non-blocking-rules.md#why-warning-if-severity-is-info-and-criticality-is-low)).

## The dashboard

```bash
uv sync --group dashboard        # once; included in --all-groups
uv run streamlit run dashboard/app.py
```

It opens at <http://localhost:8501>. The dashboard is read-only: it never changes the store, and it can stay open while validations run.

**The sidebar** sets the time window (last 24 hours, 7 days or 30 days; 7 by default) and an optional dataset to drill into. The window applies to every view except Dataset Health.

| View | Answers | What to look for after scenarios 1–9 |
|---|---|---|
| **Dataset Health** | Which datasets are in trouble right now? | `shipments` **critical**; `orders`, `products`, `signups` and the simulated dataset **degraded**; `customers`, `events`, `reviews`, `clickstream` **healthy** |
| **Recent Incidents** | What failed, how badly, and why? | Each incident's priority, score and top reason |
| **Failed Rules** | Which rules fail most often? | `orders` rules at the top after the repeated runs in scenario 3 |
| **Recurring Failures** | Is it new, or has it been happening? | `orders` rules marked *persistent* |
| **Metric Trends** | How has one rule's value moved, and what was allowed? | A dataset must be selected (see below) |
| **Quality History** | Every run of the selected dataset | The same data as `sentinel history` |

### How health is decided

Health comes from the dataset's **latest** run and the **priority** of its incidents, not just pass or fail:

| Health | When |
|---|---|
| healthy | The latest run produced no incidents |
| degraded | Its worst incident is INFO, WARNING or HIGH |
| critical | Its worst incident is CRITICAL |
| unknown | Never validated |

That's why `products` is only *degraded*: its failure is real but was prioritized WARNING. A low-priority failure shouldn't look as alarming as a critical one.

### Recurring failures

Within the selected window, each failing rule is classified as:

| Classification | Meaning |
|---|---|
| first occurrence | Failed once |
| recurring | Failed two or more times, but its latest run passed (it comes and goes) |
| persistent | Failed two or more times, and is still failing |

*Persistent* is the one to act on first: the problem hasn't gone away on its own.

### Metric trends and threshold bands

Select a dataset in the sidebar, then pick a rule. The chart shows:

- **the line**: the value the rule measured on each run;
- **the shaded band**: the range the threshold allowed on that run. For adaptive strategies the band moves, because it is recomputed from history every run;
- **red points**: runs where the rule did not pass.

Good things to look at:

| Dataset → rule | What you'll see |
|---|---|
| `simulated_orders_duckdb` → `volume_seasonal` | A band that follows the weekly rhythm, wide where a weekday has little history and tight later, with red points on the anomaly days |
| `simulated_orders_duckdb` → `volume_statistical` | A band so wide that the anomalies stay inside it: the visual version of "0/3 caught" |
| `simulated_orders_duckdb` → `nulls_median_mad` | A flat, narrow band and a single red spike |
| `signups` → `row_count_seasonal` | The weekday/weekend pattern of the 28 backfilled days |

**Latest threshold details** under the chart shows exactly what the strategy computed on its most recent run.

## Try it

- **Reproduce a recurring failure.** Blank one email in `data/customers.csv` (scenario 1), run `validate customers` twice, restore the file, and run it again. `customers` appears under Recurring Failures as *recurring*, and its health returns to healthy.
- **See an empty store.** Point Sentinel at a new database and run anything:
  ```bash
  docker compose exec postgres createdb -U sentinel scratch
  SENTINEL_DATABASE_URL=postgresql://sentinel:sentinel@localhost:5432/scratch uv run sentinel validate customers
  ```
  ```text
  Store schema is at revision none, expected 0001. Run `sentinel db upgrade`.
  ```
  Exit code `3`: Sentinel refuses to run against a store whose tables aren't set up, rather than failing halfway. Run `sentinel db upgrade` with the same URL to fix it.

**Next:** [11. Many pipelines at once](11-concurrent-runs.md)
