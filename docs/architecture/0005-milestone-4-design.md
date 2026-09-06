# Sentinel — Milestone 4 Architecture (Phase A — Design Review)

**Status:** Design approved (2026-09-06). Phase B (implementation) not started.
**Scope:** Milestone 4 (Threshold Intelligence) — historical-metrics access, four adaptive
`ThresholdStrategy` implementations (Percentage Deviation, Statistical Mean/StdDev, Median/MAD,
Seasonal Baseline), and a synthetic experiment framework demonstrating when adaptive thresholds
reduce false positives without hiding genuine anomalies.

---

## Part 1 — Headline Finding

`ThresholdStrategy.evaluate()` has carried a `history: Sequence[Metric] = ()` parameter since
Milestone 0 (`thresholds/base.py`). `StaticThresholdStrategy` already accepts and ignores it;
`DummyThresholdStrategy` in the shared test doubles already threads it through. The Protocol this
milestone needs was written three milestones ago and has simply never been fed.

That reframes the milestone: **the `ThresholdStrategy` interface itself does not change.** The
work is entirely in (a) building the seam that supplies `history` before `evaluate()` is called,
and (b) the four strategies that make use of it.

Inspected before proposing anything: `thresholds/base.py`, `thresholds/static.py`,
`thresholds/registry.py`, `domain/metric.py`, `domain/events.py`, `domain/policy.py`,
`orchestration/orchestrator.py`, `persistence/{engine,schema,reader,writer,mapping}.py`,
`rules/base.py` + `row_count.py`/`null_rate.py`, `cli/main.py`, `cli/bootstrap.py`,
`tests/unit/doubles.py`, `tests/unit/thresholds/test_static.py`.

---

## Part 2 — Why Historical Metrics Need an Abstraction (Not a Direct DB Query)

Two independent reasons, not one:

1. **Testability precedent already set.** `test_static.py` and `doubles.py` construct `Metric`
   and `ThresholdConfig` in memory and call `.evaluate()` directly — no connection, no fixtures.
   If an adaptive strategy queried DuckDB itself, that testing style breaks for every adaptive
   strategy; every test would need a live or faked persistence connection to exercise pure
   arithmetic over a list of floats.
2. **Same layering discipline `DataSource` already enforces on the other side of a `Rule`.** A
   `Rule` doesn't know whether it's reading DuckDB, Postgres, or CSV. A `ThresholdStrategy`
   shouldn't know whether history came from DuckDB, Postgres, or a synthetic experiment script.

Clarification worth stating explicitly: `PostgresDataSource` (Milestone 3) is about the **dataset
being validated**. Sentinel's own metrics store (`persistence/engine.py`) is DuckDB-only, always —
unchanged by this milestone. So this abstraction does not need `DataSource`'s registry-of-adapters
pattern; it needs exactly one seam so strategies stay pure and unit-testable.

### Proposed abstraction

```python
# sentinel/thresholds/history.py — no duckdb import, so thresholds/ stays DB-agnostic
class HistoricalMetricsSource(Protocol):
    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]: ...
```

Concrete implementation (`persistence/history.py`, Phase B Task 2 — done) queries the existing
`metrics` table joined to `validation_runs` on `validation_run_id`, filtered directly on
`validation_runs.dataset_id` (already the same id `HistoricalMetricsSource.get_history` is scoped
by — see below). No further join to `datasets` is needed, unlike `persistence/reader.py`'s
`list_recent_runs`, which filters by a Dataset's *name* rather than its id and therefore does need
that extra join. **No schema migration.**

### Scoping key: `(dataset_id, metric_name)`

Confirmed `metric_name` is always `config.name` — the rule's own declared name in the policy
(`row_count.py`, `null_rate.py` both set it this way). That is already the correct granularity:
two `null_rate` rules on different columns get different names and therefore independent
histories, with no changes needed anywhere else. Policy version is ignored for history lookup,
matching `list_recent_runs`'s existing precedent.

History is fetched capped at a bound (`limit`, default 90 rows, newest-first) at the source level,
so a long-lived dataset never pulls an unbounded number of rows per validation run. Each
strategy's own `min_history` param decides how much of that window it actually needs.

### Orchestrator change

The only change to `orchestration/orchestrator.py`: for each rule, fetch history for
`(dataset.id, rule_config.name)` via an injected `HistoricalMetricsSource`, and pass it as the
third argument to `evaluate()`. This is uniform across every rule regardless of which strategy
runs — `StaticThresholdStrategy` still ignores it, so **Milestone 0–3 behavior is unchanged
byte-for-byte.** No strategy-specific branching is introduced in the orchestrator (constraint
10), because the orchestrator never inspects which strategy it's calling.

`ValidationOrchestrator.__init__` gains an optional `history_source: HistoricalMetricsSource`
parameter, defaulting to a no-op source that always returns `()` — so every existing construction
site (tests included) keeps working unmodified. `cli/main.py`'s `validate` command builds the real
DuckDB-backed source from `context.conn` (already available in `AppContext`) and passes it in.

---

## Part 3 — Strategy Configuration

Following `StaticThresholdStrategy`'s existing idiom exactly: each strategy reads its own keys
from `ThresholdConfig.params` directly and raises a clear error if something required is missing.
No new Pydantic config models — `ThresholdConfig.params` was deliberately left as an open dict for
exactly this reason (see `domain/policy.py`'s own docstring).

| Strategy | `strategy` value | params |
|---|---|---|
| Percentage Deviation | `percentage_deviation` | `max_deviation` (required float), `min_history` (default 1) |
| Statistical (Mean/StdDev) | `statistical` | `n_sigma` (default 3.0), `min_history` (default 2) |
| Median/MAD | `median_mad` | `n_mad` (default 3.0), `min_history` (default 2) |
| Seasonal Baseline | `seasonal` | `dimension` (only `"day_of_week"` supported), `n_sigma` (default 3.0), `min_history` (default 2, applied per bucket) |

**Percentage Deviation's baseline is the mean of fetched history**, not the single most recent
value — deterministic, makes use of "historical metrics" (plural) as the milestone brief names
the section, and gives `min_history` a real guard to check. (Flagged as a definition choice, not
inferred from the brief's single-baseline example, which was ambiguous between the two readings.)

### Shared statistics, kept internal

Statistical, Median/MAD, and Seasonal all need "compute bounds from a list of numbers." Rather
than duplicate that arithmetic three times, pure helper functions live in a private
`thresholds/_stats.py` (`mean_stddev_bounds`, `median_mad_bounds`) with no registry entry of its
own — each strategy's `evaluate()` stays as thin as `static.py`'s is today, calling into shared
math rather than reimplementing it. Seasonal becomes "bucket history by weekday, call the same
bound function per bucket."

---

## Part 4 — Recording Baseline/Bounds on `QualityEvent`

`ThresholdResult.expected` is a plain human-readable string today, and its own docstring already
anticipates this: *"Revisit if a consumer needs it structured."* Milestone 3 hit the identical
problem on the `Metric` side and solved it with `Metric.details: str | None` — JSON, optional,
doesn't touch pass/fail logic, not persisted that milestone.

Applying the same fix symmetrically: `ThresholdResult.details: str | None = None` (JSON: baseline,
bounds, deviation, sample size, method, n_used). `expected` stays the short human string (e.g.
`"row_count within [820.0, 1180.0] (mean=1000.0, ±3σ, n=30)"`); `details` is the machine-readable
backing data. Mirrors `Metric.details` exactly, including the same deferral: **not persisted this
milestone** (no `quality_events.details` column) — visible on the in-memory `QualityEvent` for the
CLI and the experiment framework, same scope `Metric.details` shipped with in Milestone 3.

---

## Part 5 — Exceptions

`ThresholdConfigError` covers a policy author's mistake (missing/invalid params). Insufficient
history is a *data* problem, not a config problem, and conflating the two would mislead whoever
handles the error. New exception, `InsufficientHistoryError`, added to `thresholds/base.py`
alongside `ThresholdConfigError`, raised when `len(history) < min_history` (or, for Seasonal, when
a specific weekday bucket falls short).

---

## Part 6 — Statistical Edge Cases

- **Baseline = 0 (Percentage Deviation):** `actual == 0 and baseline == 0` → PASS (0% deviation,
  degenerate but correct). `baseline == 0 and actual != 0` → deviation is undefined/infinite;
  treated as FAIL rather than raising, with `details` explaining why (not a config error — the
  strategy can still reach a verdict).
- **Zero variance in history** (stddev = 0 or MAD = 0): bounds collapse to a point; any deviation
  fails. Mathematically correct, documented as a named limitation rather than treated as a bug.
- **Insufficient history:** `InsufficientHistoryError` (Part 5), applied uniformly, including
  per-bucket for Seasonal.
- **Non-normal distributions:** `statistical` (Mean/StdDev) documents, in its own docstring, that
  it assumes approximate normality and points at `median_mad` as the robust alternative — not
  fixed, only documented, per the milestone brief's explicit instruction.
- **Negative values:** deviation sign follows the signed difference from baseline; no special
  casing beyond what the arithmetic already gives.

---

## Part 7 — Synthetic Evaluation Framework

Confirmed strategies are tested by constructing `Metric` + `ThresholdConfig` directly and calling
`.evaluate()` — no `Rule`, `DataSource`, orchestrator, or persistence involved (Part 1). The
experiment framework follows the same shape and needs none of those either:

1. Generate synthetic `Metric` histories directly, fixed random seed, each point carrying a
   ground-truth label (`is_anomalous: bool`) that exists only in the experiment — this label has
   no home in the domain model and does not get one.
2. Run each configured strategy's `.evaluate()` against each scenario point, using preceding
   synthetic points as `history`.
3. Compare predicted status (`FAIL` = flagged) against ground truth; tabulate TP/FP/TN/FN and
   rates (FPR, FNR where applicable).
4. Write results to a deterministic, regenerable file (`docs/experiments/milestone-4-results.md`),
   generated by the runner — never hand-typed.

Layout: `experiments/threshold_intelligence/{scenarios.py, runner.py}`. A pinning test
(`tests/unit/experiments/test_runner.py`) asserts the documented expected outcomes as real
assertions (e.g. "Scenario B: static → ≥1 false positive, seasonal → 0 false positives";
"Scenario C: adaptive strategies → FAIL"), so "reproducible evidence" is CI-guarded, not just a
markdown claim that can silently drift.

### Scenarios (per milestone brief, confirmed unchanged)

| Scenario | Shape | Static | Adaptive |
|---|---|---|---|
| A — Stable | ~1000 ± small noise | PASS | PASS |
| B — Seasonal (weekday ~1000, weekend ~500) | global static/global baseline flags weekends | false positive(s) | Seasonal → correctly PASS |
| C — Genuine anomaly (baseline ≈1000, spike to 1800) | — | FAIL (expected) | FAIL (expected) |
| D — Historical outlier in the baseline window | one extreme historical point | — | Mean/StdDev skewed by the outlier vs. Median/MAD robust — both computed and compared explicitly |

---

## Part 8 — Phase B Task Sequence

1. `HistoricalMetricsSource` Protocol (`thresholds/history.py`) + no-op default implementation.
2. DuckDB-backed `HistoricalMetricsSource` implementation in `persistence/` (query + tests, no
   schema change).
3. Orchestrator wiring: optional `history_source` dependency, fetch-and-pass per rule; CLI wiring
   in `cli/bootstrap.py`/`cli/main.py`. Verify Milestone 0–3 tests still pass unmodified.
4. `ThresholdResult.details` field (+ `InsufficientHistoryError`, `thresholds/_stats.py` helpers).
5. Percentage Deviation strategy + unit tests (incl. baseline=0, negative values, insufficient
   history).
6. Statistical (Mean/StdDev) strategy + unit tests (incl. zero variance).
7. Median/MAD strategy + unit tests, including the explicit Mean/StdDev-vs-Median/MAD divergence
   on an outlier-contaminated history (Scenario D's math, tested directly).
8. Seasonal Baseline strategy + unit tests (per-weekday bucketing, per-bucket insufficient
   history).
9. Synthetic scenarios A–D (`experiments/threshold_intelligence/scenarios.py`) + deterministic
   seed.
10. Experiment runner: confusion matrix, rates, results file generation
    (`experiments/threshold_intelligence/runner.py`).
11. Pinning tests on documented scenario outcomes (`tests/unit/experiments/test_runner.py`).
12. Documentation: this doc's "Definition of Done" answers (Part 9), `docs/experiments/milestone-4-results.md`,
    README status line updated. No CLI change needed -- history is fetched and passed internally by the
    orchestrator; no new flags or user-facing behavior were introduced.

Each task implemented and confirmed individually, per the project's existing working convention —
no batch implementation across tasks.

---

## Part 9 — Definition of Done

Task 12 of Phase B. Answered from the actual numbers in `docs/experiments/milestone-4-results.md`
(regenerated by `experiments/threshold_intelligence/runner.py`, pinned by
`tests/unit/experiments/test_runner.py`) — every claim below cites a real, reproduced
confusion-matrix count, not an expected or hand-waved one.

**When do static thresholds fail?**

When the "normal" range genuinely isn't a single fixed band. Scenario B is the clean case: a
static `[800, 1200]` range tuned for weekday traffic (~1000) has no notion that ~500 is *also*
normal on weekends, so it flags all 12 weekends as false positives over 6 weeks. Static isn't
wrong about the weekday days — it's wrong about treating every day the same. Scenario D shows the
opposite edge: static's fixed bound is completely indifferent to history, which is a *strength*
there (it flags both occurrences of the historical-outlier value with 0 false negatives) — static
only fails when the right answer depends on context static was never given.

**When does Percentage Deviation work well — and when does it not?**

It works when the metric has one genuine baseline and deviations from it matter in relative
rather than absolute terms (e.g. "row count should be within 15% of its recent average" scales
correctly whether the average is 100 or 100,000, where a fixed absolute band wouldn't). It fails
for exactly the same reason static does, and worse: Scenario B is its worst result of the four
adaptive strategies (26 false positives, more than static's 12) because it has no seasonality
*and* no tolerance for spread — a single blended mean-of-history baseline sitting between two
real clusters means both clusters routinely miss its narrow band. Percentage Deviation is a
one-baseline strategy; multi-population data needs a different one.

**When are Mean/StdDev (Statistical) thresholds appropriate?**

When the underlying data is genuinely unimodal and roughly symmetric — a single unbroken bell
curve with occasional real outliers. That is what Scenario D's first evaluation demonstrates
cleanly: with 5 clean historical points, mean/stddev bounds are tight and the 5000 outlier is
caught immediately. The precondition that makes it appropriate is exactly what Scenario B
violates (a genuinely bimodal weekday/weekend population): mixing two populations inflates the
standard deviation enough to swallow both clusters *and* the real anomaly, producing the
milestone's most important finding — 0 false positives paired with 1 false negative. A quiet
strategy is not the same thing as a correct one.

**Why are Median/MAD more robust to outliers than Mean/StdDev?**

Because a single extreme value can move a median by at most one rank position, while it can move
a mean by an arbitrarily large amount — and standard deviation, being computed from squared
distances to that already-shifted mean, is dragged even further. `_stats.py`'s two bound
functions make this concrete on the same history used throughout this milestone
(`[1000, 1020, 980, 1010, 1005, 5000]`): mean/stddev bounds come out to roughly `[-3226, 6565]`
(the outlier sits *inside* its own bounds), while median/MAD bounds come out to `[963, 1052]`
(the same outlier is correctly rejected). Scenario D's confusion matrix is this same effect
playing out sequentially: once the first 5000 has entered Statistical's history, its own bounds
widen enough that the *second* 5000 passes (1 true positive, then 1 false negative) — Median/MAD
catches both, because one extreme value never has enough leverage over a median to protect its
own repeat.

**When does seasonality matter?**

When the metric has a real, recurring, non-noise structure tied to a calendar dimension — Scenario
B's weekday/weekend split is the textbook case. There, Seasonal is the only strategy that gets
both halves of the job right at once: it catches the genuine anomaly (1 true positive, 0 false
negatives) *and* has by far the fewest false positives of any strategy (2, versus 12 for static
and median/MAD and 26 for percentage deviation). But seasonality-awareness isn't free: it costs
sample size. Scenario A splits 30 stable days into 7 day-of-week buckets of only 4-5 points each,
small enough that normal noise alone produces 1 false positive purely from a thin sample — a real
cost of bucketing, not a bug, and Scenario D shows the extreme version of that cost (7 buckets of
exactly 1 point each means *zero* evaluations are possible; every one of the 7 points is
correctly skipped as `InsufficientHistoryError` rather than guessed). Seasonal only pays for
itself once enough history has accumulated *per bucket*, not just in total.

**What false positives can adaptive thresholds concretely reduce?**

Precisely the class Scenario B was built to isolate: false alarms caused by a static bound that
doesn't know the "normal" range shifts with a recurring, predictable factor. Static's 12 weekend
false positives over 6 weeks (one every single weekend) drop to 2 under Seasonal — the same
underlying data, the same 6 weeks, a ~6x reduction, with zero cost in missed detections (both
strategies catch the one genuine anomaly). That is the milestone's headline result and the
reason all the other numbers in this document exist: it is a real, reproduced count, not a
theoretical claim about what adaptive thresholds are supposed to do.

**What failure modes and limitations remain?**

Three, and this milestone is deliberately built to surface all three rather than hide them behind
a single flattering scenario:

1. *Not every adaptive strategy is safe by default.* Scenario B shows two different adaptive
   strategies doing *worse* than static on the same data — Percentage Deviation (26 false
   positives) and global Median/MAD (12, matching static) — because "adaptive" only helps when the
   strategy's own assumption (one baseline; robustness to rare outliers) actually matches the
   data's shape. Neither is aware of a *recurring* pattern; both are just differently blind to it.
2. *Global Mean/StdDev can hide a real anomaly instead of just tolerating noise.* Scenario B's
   1 false negative on Statistical is the sharpest limitation in this whole milestone: a strategy
   can report zero false positives for the wrong reason (bounds too wide to be useful) rather than
   the right one (bounds correctly calibrated). Reading "0 false positives" alone, without also
   checking false negatives, is actively misleading here.
3. *Statistical's own history is corruptible by what it's supposed to catch.* Scenario D's
   statistical result (catches the first 5000, misses the second) means a strategy's history isn't
   a neutral record of "normal" once an anomaly has been let through — every uncorrected anomaly
   that enters history makes the strategy less likely to catch the same anomaly again. Median/MAD
   and Static don't have this problem (for different reasons — rank-robustness and history-blindness
   respectively), but any future mean/stddev-based strategy inherits it unless anomalous points are
   excluded from the history that feeds it, which this milestone's history source deliberately does
   not attempt (that's a real, out-of-scope design question for whichever milestone adds
   incident/event feedback into the history pipeline).

None of these are implementation bugs — they're the actual, measured behavior of each strategy's
stated method, which is the point of building the synthetic framework instead of asserting the
conclusion.

### Coverage

- Historical Metrics access: `HistoricalMetricsSource` Protocol + `NullHistorySource` +
  `DuckDBHistoricalMetricsSource`, wired through the orchestrator with no Rule change (Tasks 1–3).
- Percentage Deviation, Statistical, Median/MAD, Seasonal Baselines: all four implemented as
  `ThresholdStrategy`s, registered, unit-tested including edge cases (Tasks 4–8).
- Synthetic Evaluation Framework: four scenarios, a confusion-matrix runner, a generated results
  document, and pinning tests that fail if the documented numbers ever silently drift (Tasks 9–11).
- The demonstration the milestone asked for — *why* adaptive thresholds reduce false positives
  compared with static ones, including the cases where they don't — is answered above with cited,
  reproduced numbers, not asserted.
