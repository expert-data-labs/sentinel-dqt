# 4. Thresholds that learn: `signups`

**The situation.** The growth team gets about 1000 signups on a weekday and about 520 at the weekend. What counts as a normal count depends on the day. A fixed `min: 900` would raise an alarm every Saturday, and a fixed `min: 400` would miss a weekday where half the signups went missing. You want limits that learn what normal looks like from history.

**You'll learn:** the four adaptive threshold strategies, why they disagree, how to compare them safely in production with "shadow" rules, and why history is needed before they can work.

```bash
uv run sentinel validate signups
```

> Run `uv run python -m examples.setup` first. Adaptive strategies refuse to judge without history, and the setup backfills 28 days of it.

---

## Where the history comes from

Adaptive strategies compare today's value with the same rule's past values. A brand new rule has none, so `examples.setup` writes 28 daily runs for the last four weeks: about 1000 on weekdays and about 520 at weekends, each with a little noise. Those are ordinary stored runs, exactly as if the policy had been running for a month.

Today's `data/signups.csv` has **1000 rows**, a perfectly normal weekday.

## The policy: one metric, five opinions

Every rule measures the same thing (row count). Only the threshold differs:

```yaml
- name: row_count_sanity               # blocking: a hard floor that never moves
  type: row_count
  severity: critical
  threshold: {strategy: static, min: 100}

- name: row_count_vs_recent_mean
  type: row_count
  blocking: false
  threshold: {strategy: percentage_deviation, max_deviation: 0.10, min_history: 7}

- name: row_count_statistical
  type: row_count
  blocking: false
  threshold: {strategy: statistical, n_sigma: 3, min_history: 7}

- name: row_count_median_mad
  type: row_count
  blocking: false
  threshold: {strategy: median_mad, n_mad: 3, min_history: 7}

- name: row_count_seasonal
  type: row_count
  blocking: false
  threshold: {strategy: seasonal, n_sigma: 3, min_history: 3}
```

| Strategy | Allowed range | In plain words |
|---|---|---|
| `static` | Fixed `min` / `max` | "Never fewer than 100." |
| `percentage_deviation` | Mean of history ± `max_deviation` | "Within 10% of the usual average." |
| `statistical` | Mean ± `n_sigma` standard deviations | "Not unusually far from the average, given how much it normally varies." |
| `median_mad` | Median ± `n_mad` scaled median absolute deviations | The same idea, but built on the median, so a few past outliers can't distort it. |
| `seasonal` | Mean ± `n_sigma` standard deviations **of the same weekday** | "Normal *for a Friday*." |

`min_history` is how many past values a strategy needs before it will judge. For `seasonal` it counts per weekday: `min_history: 3` needs three past Fridays.

**The shadow-rule pattern.** The four adaptive rules are `blocking: false`. They are evaluated, stored and visible, but can't fail the pipeline. Only the static sanity check is enforced. This is how you trial a new strategy in production: run it in shadow next to what you trust, compare verdicts for a few weeks, then promote the one that works.

## What you'll see (on a weekday)

```text
Dataset: signups
Run ID:  fe8b216e-f298-479b-b9b0-133f0ee89aae
Result:  PASS

  ✓ row_count_sanity  actual=1000  expected: row_count_sanity >= 100
  ✗ row_count_vs_recent_mean  actual=1000  expected: row_count_vs_recent_mean within ±10% of baseline 859.4
      priority=WARNING score=47.2  Dataset criticality: MEDIUM
  ✓ row_count_statistical  actual=1000  expected: row_count_statistical within [188.1, 1531] (mean=859.4, ±3σ, n=28)
  ✓ row_count_median_mad  actual=1000  expected: row_count_median_mad within [878.8, 1092] (median=985.5, ±3 scaled MAD, n=28)
  ✓ row_count_seasonal  actual=1000  expected: row_count_seasonal within [957, 1044] for Friday (mean=1001, ±3σ, n=4)
```

Exit code `0`. Your exact numbers depend on the date you run the setup, but the pattern is the same. Each `expected` line shows the range the strategy computed today, which is the best way to understand it:

| Rule | Verdict | Why |
|---|---|---|
| `row_count_sanity` | ✓ | 1000 is above 100. Static rules don't care about history. |
| `row_count_vs_recent_mean` | ✗ | Its baseline, 859, averages weekdays *and* weekends, so it is wrong on every day of the week: a normal weekday is 16% above it and a normal weekend 40% below. |
| `row_count_statistical` | ✓ | It passes, but look at the range: 188 to 1531. The weekday/weekend swing inflates the standard deviation so much that a day with half the usual signups would still pass. |
| `row_count_median_mad` | ✓ | The median (985) sits among the weekdays, which are the majority, so weekdays pass. A normal weekend (~520) is far outside 879–1092 and would fail every Saturday. |
| `row_count_seasonal` | ✓ | It compares Friday only with past Fridays (mean 1001, range 957–1044). A tight range that is still correct. |

**Only `seasonal` understands the weekly pattern**: it is both tight enough to catch real problems and right on every day of the week. The general lesson is to pick the strategy that matches the *shape* of your data. The [Choosing a strategy](../components/thresholds.md#choosing-a-strategy) table summarizes which shape suits which strategy.

## On a weekend

Run the same command on a Saturday or Sunday and the 1000 rows are now *abnormal* (the history says ~520). `row_count_seasonal` fails, while `row_count_median_mad` passes, because it only knows the weekday level. Both are non-blocking, so the run still exits `0`.

## Try it

Keep a copy first: `cp data/signups.csv /tmp/signups.csv`.

- **A weekday that looks like a weekend.** Keep 520 rows: `head -n 521 /tmp/signups.csv > data/signups.csv`. On a weekday, `seasonal` fails (it expects ~1000 today) and `median_mad` fails too; `statistical` still passes. On a weekend, `seasonal` passes.
- **An outage.** Keep 300 rows: `head -n 301 /tmp/signups.csv > data/signups.csv`. Every adaptive rule except `statistical` fails, and the sanity check still passes. A 70% drop sits inside `statistical`'s 188–1531 range: this is the strategy that misses real problems here.
- **Read its history.** `uv run sentinel history signups` shows the 28 backfilled runs and today's. Today's run is listed as `FAIL` with `failed: row_count_vs_recent_mean`: the stored status reports every failure, even though the exit code ignored it.

Restore with `cp /tmp/signups.csv data/signups.csv`.

## Starting an adaptive rule without a backfill

Without history, an adaptive rule stops the whole run with an "insufficient history" error, because it refuses to guess. In a real project, start each rule as `static` with a generous limit, run it until it has `min_history` results (per weekday, for `seasonal`), then switch its strategy while **keeping the same rule name**. History is stored by rule name, so it carries over. See [Cold start](../components/thresholds.md#cold-start).

One day of results only tells you so much. [Scenario 9](09-simulator-adaptive-thresholds.md) replays eight weeks with known anomalies and scores each strategy.

**Next:** [5. Checking a Postgres table](05-events-postgres.md)
