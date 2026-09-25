# Milestone 6 — Observability: Phase A Design Review

Per this milestone's own instructions ("Start With Design Review — Do Not Implement Yet", step 6:
"STOP and present the design for review"), nothing below has been implemented. This document is
the output of steps 1-5 only: inspecting the real, current Sentinel architecture (not a
from-memory summary of it) and proposing the minimal observability/query layer and dashboard
technology needed to satisfy the milestone's Definition of Done. Every claim about "what already
exists" below was checked against the actual files in your working tree this session, not assumed
from earlier milestones' design docs.

## Part 1 — What Actually Exists in the Persistence Layer Today

Four tables, all created by `persistence/schema.py`'s `ensure_schema()` (idempotent
`CREATE TABLE IF NOT EXISTS`, applied in dependency order, no Alembic — the same "no migration
framework until there's real migration history to manage" stance the file's own docstring states):

```text
datasets          id (PK), name, source_type, environment, owner, criticality, config_reference
validation_runs   id (PK), dataset_id (FK), policy_version, started_at, finished_at, status
metrics           id (PK), validation_run_id (FK), metric_name, value, computed_at
quality_events    id (PK), validation_run_id (FK), metric_id (FK), status, expected,
                  strategy_type, severity, blocking
```

`persistence/writer.py`'s `persist_validation_run()` is the only writer, one transaction per
`sentinel validate` invocation, upserting the dataset row and inserting one `validation_runs` row,
one `metrics` row and one `quality_events` row per `QualityEvent`. Three existing read paths sit on
top of these tables today, and each is a useful precedent for how Observability's own queries
should be shaped:

- `persistence/reader.py` (`list_recent_runs`) — powers `sentinel history`; filters by
  `datasets.name`, joined to `validation_runs`, with one extra query per run for its failed rule
  names (a deliberate, documented N+1 — "a single `list()`/`FILTER` aggregate query would trade a
  few extra local queries for real complexity" at `limit=10`).
- `persistence/history.py` (`DuckDBHistoricalMetricsSource`) — backs adaptive threshold strategies;
  filters directly on `validation_runs.dataset_id` (no join to `datasets`, since `dataset_id` is
  already the same string as `Dataset.id`).
- `persistence/failure_history.py` (`DuckDBFailureHistorySource`) — backs incident prioritization's
  frequency signal; same join shape as `history.py`, returns raw `Status` outcomes for one
  `(dataset_id, metric_name)` pair, most recent first, row-count-limited (not time-windowed).

**None of the three existing read paths reconstructs a domain object graph.** Each returns a thin,
purpose-built projection (`RunSummary`, a `Sequence[Metric]`, a `Sequence[Status]`) — reader.py's
own docstring is explicit that this is deliberate ("Nothing today needs a full `ValidationRun`
rebuilt from stored rows, and building that mapper would solve a problem nothing asks for yet").
Observability Queries should follow the identical discipline: presentation-shaped read models, not
domain objects, and not a generic repository either.

## Part 2 — Mapping the Six Required Views to What's Persisted

| View | Backing data | Already persisted? |
|---|---|---|
| Dataset Health | latest `validation_runs.status` per dataset; highest `IncidentPriority` among that run's non-PASS events | **Partially** — run status yes, incident priority **no** |
| Quality History | per-run passed/failed counts (aggregate `quality_events` by `validation_run_id`); highest incident priority per run | **Partially** — counts yes, priority **no** |
| Metric Trends | `metrics.value` over `computed_at`, filtered by dataset+metric name; baseline/bounds alongside the observed value | **Partially** — the value/time series yes, baseline/bounds **no** |
| Failed Rules | count of non-PASS `quality_events` by (dataset, rule), latest failure timestamp, current priority | **Partially** — count/timestamp yes, priority **no** |
| Incident History | timestamp, dataset, rule, priority, score, reason, per incident | **No — nothing about Incident is persisted at all** |
| Recurring Failures | (dataset, rule) pairs with 2+ non-PASS events in a time window | **Yes**, fully derivable from `quality_events`/`metrics`/`validation_runs` as they stand |

Five of six views need something that isn't in the store yet. This isn't six separate gaps —
it's two, each hit by multiple views:

## Part 3 — The Headline Finding: Two Deferred Facts Are Now Due

Milestone 5's own design doc (`docs/architecture/0006-milestone-5-design.md`, Part 12, Open
Questions 4 and 5) made two decisions that were correct *for Milestone 5* and were explicitly
flagged as deferred rather than solved:

1. **`Incident` (priority, score, components, reasons) was never persisted.** Open Question 4 asked
   "persist Incident to DuckDB this milestone... or keep in-memory only, deferred to M6" and the
   recommendation — which you approved — was "defer: not in M5's own Definition of Done." M6 is
   the milestone that Definition of Done pointed to. `ValidationRun.incidents` already holds the
   computed `Incident` tuple in memory (Milestone 5 built this), so nothing needs to be
   *recomputed* — only persisted, in the same transaction `persist_validation_run` already runs.

2. **`ThresholdResult.details` (the adaptive strategies' computed baseline/bounds, plus Milestone
   5's addition of the same for `StaticThresholdStrategy`) was never persisted.** `domain/events.py`
   says so directly in `ThresholdResult`'s own docstring: "Not persisted this milestone either (no
   `quality_events.details` column)... visible on the in-memory QualityEvent for the CLI and the
   synthetic experiment framework." Metric Trends' requirement to show "Expected Baseline /
   Threshold / Bounds alongside the observed metric" needs exactly this, for every strategy
   uniformly (Milestone 5 added `details` to `StaticThresholdStrategy` specifically to make it
   available across *all* strategies, not only the four adaptive ones — that investment pays off
   again here).

Neither of these is new business logic and neither is scope creep. Both are additive schema
growth over facts Sentinel already computes — exactly the "Observability is a consumer of existing
runtime facts" principle this milestone's own brief states, applied to the two facts that
happen not to have a table/column yet. The alternative — deriving incident priority or threshold
bounds freshly inside a dashboard query — is explicitly what the brief forbids ("must NOT...
reimplement incident-prioritization logic... calculate thresholds").

**A technical note that matters for how these get added:** `ensure_schema()`'s
`CREATE TABLE IF NOT EXISTS` pattern creates a *new* table if it's missing, but does nothing to an
*already-existing* table — it will not retroactively add a column to `quality_events` in a
`sentinel.duckdb` file that was created before this migration (and your repo already has one, from
this session's own testing). DuckDB supports `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, which is
the smallest mechanism that closes this gap without introducing a real migration framework —
Phase B should add one such statement to `ensure_schema()` alongside the existing `CREATE TABLE`
statements, for the same reason those are idempotent: safe to run on every CLI invocation, on both
a brand-new store and your existing one.

## Part 4 — Proposed Schema Changes

Two additive changes, both backward-compatible (nothing about the existing four tables' meaning
changes, no existing row becomes invalid):

**New `incidents` table**, one row per `Incident` (i.e., per non-PASS `QualityEvent` — mirrors
`quality_events`' own one-row-per-event shape):

```sql
CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY,
    validation_run_id UUID NOT NULL REFERENCES validation_runs(id),
    quality_event_id UUID NOT NULL REFERENCES quality_events(id),
    priority VARCHAR NOT NULL,
    score DOUBLE NOT NULL,
    components VARCHAR NOT NULL,   -- JSON-encoded IncidentScoreComponents
    reasons VARCHAR NOT NULL       -- JSON-encoded tuple[str, ...]
)
```

`priority` and `score` get real columns because every required view filters or sorts on one of
them (`WHERE priority = 'CRITICAL'`, `ORDER BY score DESC`, "highest priority per run"). `components`
and `reasons` get one JSON column each, following the exact precedent `Metric.details` and
`ThresholdResult.details` already set: structured context nothing needs to query column-by-column,
so it doesn't need column-by-column storage. No `created_at` — deliberately, mirroring
`quality_events`' own lack of one: an incident's timestamp is the `validation_runs` row it belongs
to (joined via `validation_run_id`, exactly like `metrics.computed_at` already stands in for
`quality_events`' timestamp today).

**One new column on the existing `quality_events` table:**

```sql
ALTER TABLE quality_events ADD COLUMN IF NOT EXISTS details VARCHAR
```

This is `QualityEvent.threshold_details` (the `ThresholdResult.details` passthrough), written
verbatim — the dashboard never recomputes a bound, it reads back the one the threshold strategy
already computed at validation time.

**Not proposed:** persisting `Metric.details` (the Rule-observed diff data, e.g. schema-validation
mismatches). No required view asks for it; adding a column nothing reads is exactly the kind of
premature schema growth the rest of this codebase has consistently avoided.

**Backfill:** rows written before this migration will have `details = NULL` forever — there is no
way to recover a bound that was never computed and stored. This is a known, permanent, and
acceptable gap for historical rows; every row from this point forward carries it. Worth stating
explicitly rather than leaving implicit.

## Part 5 — Query Layer Architecture

**Recommendation: one new top-level package, `sentinel/observability/`**, parallel to
`sentinel/orchestration/` and `sentinel/prioritization/` — not folded into `sentinel/persistence/`.
The distinction that matters: `persistence/history.py` and `persistence/failure_history.py` are the
DuckDB-backed *implementations* of Protocols that live in `thresholds/` and `prioritization/`
specifically so that domain/application code consuming them never imports `duckdb` — a real
architectural boundary, because those Protocols could gain a second (non-DuckDB) implementation.
`ObservabilityQueryService` has no such consumer inside the domain — its only consumer is the
presentation layer (CLI or dashboard) — and, per this milestone's own layer diagram, Observability
Queries is an **application**-layer concern sitting directly on infrastructure, the same relationship
`ValidationOrchestrator` has to `datasources`/`rules`/`thresholds`. So: **a plain concrete class, no
Protocol, no registry** — identical reasoning to why `ValidationOrchestrator` and
`IncidentPrioritizer` are themselves plain classes ("a Protocol/registry earns its keep when
multiple implementations are selected at runtime by a config string... there is one algorithm
here"). Sentinel has exactly one persistence backend for its own store (always DuckDB, never
pluggable the way a Dataset's `DataSource` is) — introducing an abstraction for a second
implementation that will never exist would be indirection without payoff.

Proposed layout:

```text
sentinel/observability/
    views.py     — frozen-dataclass read models (DatasetHealthView, QualityHistoryEntry,
                   MetricTrendPoint, FailedRuleView, IncidentHistoryEntry, RecurringFailureView)
    queries.py   — ObservabilityQueryService(conn), one method per required view
    health.py    — pure functions: dataset-health derivation, recurring-failure classification
                   (no duckdb import — same "logic separate from I/O" discipline
                   sentinel.prioritization.scoring already follows)
```

`health.py` staying duckdb-free matters for testing: the *rules* for "what counts as DEGRADED" or
"what counts as recurring" become unit-testable against plain Python inputs, with `queries.py`
responsible only for fetching the right rows and handing them to `health.py`'s functions — mirrors
how `sentinel.prioritization.scoring`'s pure `*_score()` functions are tested independently of
`IncidentPrioritizer`'s orchestration.

**Time windows and testability:** every windowed query (`Quality History`, `Metric Trends`,
`Failed Rules`, `Incident History`, `Recurring Failures`) takes an explicit `as_of: datetime`
parameter rather than calling `datetime.now(UTC)` internally. The CLI/dashboard passes real
"now" at the call site; tests pass a fixed timestamp. This is a small discipline with a large
testing payoff — it's the difference between a deterministic unit test and one that's subtly
flaky depending on when it happens to run. `TimeWindow` becomes a small `StrEnum`
(`LAST_24H` / `LAST_7D` / `LAST_30D`) resolved to a cutoff via `as_of - timedelta(...)`, not an
arbitrary date-range control (per the milestone's own instruction #11).

**Dataset identity:** existing read paths are inconsistent — `reader.py` filters by
`datasets.name`, while `history.py`/`failure_history.py` filter directly by
`validation_runs.dataset_id` (which is already `Dataset.id`, no join needed). `ObservabilityQueryService`
follows the `dataset_id` convention (the majority precedent, and the more directly-indexed column) —
the CLI/dashboard resolves a typed dataset name to its `Dataset` the same way `sentinel validate`
already does (`resolve_dataset`), and passes the id down.

**Avoiding N+1** (milestone instruction #14): every view is one aggregating query with the needed
`GROUP BY`/`COUNT`/`MAX`, not a query-per-dataset or query-per-rule loop. The one deliberate,
precedented exception is `reader.py`'s existing per-run failed-rule-names query for
`sentinel history` — untouched by this milestone, and already documented as an accepted trade-off
at `limit=10`. Observability's own "Failed Rules" and "Recurring Failures" views are exactly the
aggregate versions of that same question, asked once across all datasets/rules instead of once per
run, so they get real `GROUP BY` treatment rather than repeating reader.py's shortcut at a larger
scale.

## Part 6 — Dataset Health: Deriving It Without a Second Scoring System

The milestone explicitly warns against inventing a second, complicated health-scoring system, and
asks that health be derived from existing `QualityEvent`/`Incident` state. Proposal:

```text
Dataset Health is derived from the dataset's LATEST validation run only — a "current health"
answer to "which datasets need attention right now", not a windowed aggregate (Recurring Failures
already covers the historical/windowed question).

No validation run has ever been recorded for the dataset  → UNKNOWN
Latest run has no incidents (every event PASSed)           → HEALTHY
Latest run's highest incident priority is WARNING or HIGH  → DEGRADED
Latest run's highest incident priority is CRITICAL         → CRITICAL
```

Two choices worth making explicit:

- **`IncidentPriority` drives this, not `Status`.** A dataset could have a `FAIL` event that
  Milestone 5's prioritization judged low-priority (e.g. a first-occurrence failure on a
  low-criticality dataset with a barely-breached threshold) — using raw `Status` here would
  re-introduce exactly the "every failure looks the same" flattening Milestone 5's entire premise
  argued against. Health should use the richer signal Sentinel already computes, not the raw one.
- **`UNKNOWN` is a real, separate state**, not folded into `HEALTHY`. A dataset that has literally
  never been validated is not the same claim as one that was just validated and passed — collapsing
  the two would make "HEALTHY" a lie for a dataset nobody has looked at yet.

This is one pure function over already-fetched rows (latest run's status + its incidents'
priorities), living in `observability/health.py`, with no new persisted "health" concept anywhere —
health is computed at read time from data that's already there, recomputed on every dashboard
render, never stored. These thresholds are a recommendation, not a mandate (the milestone brief
says so itself, "these are examples, not mandatory rules") — happy to adjust the WARNING/HIGH vs.
CRITICAL split if you'd rather WARNING alone stay HEALTHY, for instance.

## Part 7 — Recurring Failures: A Deliberately Different Window Than Milestone 5's

`sentinel.prioritization.frequency.summarize()` already computes "first occurrence" and
"consecutive streak" from a `Sequence[Status]` — but it's windowed by **row count**
(`FailureHistorySource.get_outcomes`'s `limit=90`, most-recent-first), because that's the right
scope for "how much precedent does *this one* failure have, right now, for prioritization." The
milestone's own definition for this view is explicitly **calendar-time-windowed**
("Recurring = same dataset + same rule failed more than once *within the selected window*" —
24h/7d/30d). These are genuinely different windowing semantics, and reusing `summarize()` here
would silently conflate them. **Recommendation: Recurring Failures gets its own aggregation
directly over `quality_events`/`metrics`/`validation_runs`, filtered by `as_of`-relative time, not
a reuse of Milestone 5's row-count-scoped abstraction** — same tables, same underlying idea
(repeated failure of one rule on one dataset), different query, because it's answering a
genuinely different question.

Proposed classification, per (dataset, rule) pair within the selected window:

```text
First occurrence:  exactly 1 non-PASS event in the window
Recurring:         2+ non-PASS events in the window
Persistent:        Recurring, AND the pair's most recent validation run (any status) also failed
                    — i.e. it's still broken right now, not just historically frequent
```

"Failure" here means a non-PASS `QualityEvent` (WARN or FAIL) — reusing the exact boundary
`ValidationOrchestrator` already draws for "does this get prioritized at all" (only non-PASS events
reach `IncidentPrioritizer`), rather than inventing a second definition of what counts as a
failure. Again: a recommendation, open to adjustment, and explicitly not a "sophisticated
failure-correlation engine" — one `GROUP BY (dataset_id, metric_name)` query with a `COUNT` and a
`MAX(computed_at)`.

## Part 8 — Choosing the Dashboard Technology

Checked what's actually available before recommending anything: `pyproject.toml`'s dependencies
today are `pydantic`, `pyyaml`, `duckdb`, `pytz`, `typer`, `psycopg[binary]` — no visualization or
web-app library at all, consistent with this project's own stated pattern of adding a dependency
only when the task that needs it lands (the comments in `pyproject.toml` say this outright about
`duckdb` and `typer`). Neither `streamlit` nor `rich` is installed anywhere reachable this session;
`matplotlib` happens to be present in one environment but isn't a declared project dependency, so it
can't be relied on in a clean `uv sync`.

Two real options, both explicitly sanctioned by the milestone brief:

**Option A — Extend the existing Typer CLI** (`sentinel dashboard [dataset]`, text/table output,
ASCII sparklines for trends using Unicode block characters). Zero new dependencies. Fully
executable and testable in this session, same as everything built for M4/M5. Weakest at the
milestone's own "make anomalies visually obvious" ask — an ASCII sparkline is a real but
noticeably cruder signal than an actual line chart.

**Option B — A minimal Streamlit app** (`dashboard/app.py`, a single file, reading only through
`ObservabilityQueryService` — never touching `duckdb` directly). One new dependency
(`streamlit`, isolated into its own optional dependency group so `sentinel validate`/`history`
users don't pull in a web framework they don't need). Genuinely the smallest widely-used tool built
for exactly this job — read-only internal reporting over a local data store — and it's the option
the milestone brief itself names first among "a lightweight Python dashboard." It directly satisfies
the "trend charts should make anomalies visually obvious" requirement in a way ASCII text
structurally can't. The real cost: this session cannot install or execute Streamlit (no
network reachable for `pip`/`uv` in either sandbox this session runs in — the same limitation
already disclosed for `duckdb`/`pytest` throughout M4 and M5), so `dashboard/app.py` itself can only
be verified by inspection (imports, structure, that it calls only `ObservabilityQueryService`
methods) plus your own `uv run streamlit run dashboard/app.py`. Every query and every piece of
health/recurrence logic underneath it is still fully, really tested regardless — the untested
surface stays confined to one thin file with no business logic in it.

**Recommendation: Option B, Streamlit.** The query/read-model layer is identical either way and is
where all the actual logic (and all of this milestone's testing requirements) lives — the choice
between A and B only changes how thin a presentation shell sits on top, and Streamlit is the
shell built for precisely this. But this is genuinely reversible and low-stakes (a few hours of
work either way, sharing 100% of the tested logic underneath), so it's listed as an open question
below rather than assumed.

## Part 9 — Testing Strategy

Matching the existing persistence-layer convention exactly (`tests/unit/persistence/test_history.py`
already does this): `ObservabilityQueryService` gets tested against a **real, temp-file DuckDB
connection** (`get_connection(tmp_path / "test.duckdb")` + `ensure_schema`), seeded via
`persist_validation_run` — not mocked — because this is the layer that actually runs SQL, and a
real connection is the right level of test double for it (contrasted with `health.py`'s pure
functions, tested with zero I/O at all).

Deterministic fixture builder covering exactly the scenarios the milestone lists: a healthy
dataset, an occasional (first-occurrence) failure, a recurring failure, a persistent failure, a
HIGH-priority incident, a CRITICAL-priority incident, multiple validation runs spanning more than
one time window, and metric history with enough points for a trend. One builder function,
reused across `test_queries.py`, `test_health.py`, and the integration test — avoiding six
different ad hoc fixture sets that each answer "is this realistic enough" slightly differently.

Per milestone instruction #17/#18: unit tests for each of the six views (correct health derivation,
correct chronological ordering, correct trend points, correct aggregation, correct incident
timestamps/priorities, correct recurrence classification), unit tests for dataset/rule/priority/
time-window filtering, and one true end-to-end integration test
(`ValidationOrchestrator.run()` → `persist_validation_run()` → `ObservabilityQueryService` →
assert the dashboard would receive the expected views) — extending
`tests/integration/test_end_to_end.py`'s existing pattern rather than inventing a new one.

The dashboard file itself (whichever option) gets no automated test, per the milestone's own
instruction ("does not need extensive browser automation... test the underlying query layer
thoroughly") — instead, a short manual smoke-test checklist in the Phase B documentation.

## Part 10 — Explicitly Out of Scope This Milestone

- Materialized views, caching, an OLAP layer, Redis, Elasticsearch — nothing here has hit a real
  performance problem to justify any of them (milestone instruction #14/#15).
- Authentication, cloud deployment, WebSockets, real-time streaming (#3) — this is a
  `streamlit run` / `sentinel dashboard` command a person runs locally and reloads.
- An arbitrary date-range picker — only the three fixed windows (#11).
- A failure-correlation engine beyond frequency counting (#10).
- Persisting `Metric.details` (Rule-observed diff data) — no required view reads it.
- Any change to `Rule`, `ThresholdStrategy`, `IncidentPrioritizer`, or the orchestrator's
  prioritization logic — Observability is purely a reader of what they've already produced and
  already persisted.

## Part 11 — Open Questions

1. **Dashboard technology:** Streamlit (recommended, Part 8) vs. extending the Typer CLI with a
   `sentinel dashboard` command (zero new dependencies, fully verifiable by me this session, but a
   cruder visual result)?
2. **`incidents` table shape:** the slim version in Part 4 (priority/score as real columns,
   components/reasons as JSON, mirroring `Metric.details`) vs. a wider version with each of the
   five score components as its own column? Recommended: the slim version — nothing in the six
   required views queries an individual component directly.
3. **Backfill:** confirm no backfill is expected for `quality_events.details` on rows already
   written before this migration (Part 4) — there's no way to reconstruct a bound that was never
   captured, so this would be documented as a permanent gap for historical rows, not solved.
4. **Dataset Health / Recurring Failure semantics** as defined in Parts 6-7 — acceptable as a
   starting point to implement and test against, same as Milestone 5's weights/boundaries were?
5. **Does the selected time window (24h/7d/30d) apply to Dataset Health at all?** Recommended: no —
   Dataset Health always reflects the latest run regardless of the window control (it's answering
   "right now", not a windowed aggregate); the window only affects Quality History, Metric Trends,
   Failed Rules, Incident History, and Recurring Failures.

## Part 12 — Proposed Phase B Task Sequence

1. Schema: add the `incidents` table and the `quality_events.details` column to
   `persistence/schema.py` (idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN
   IF NOT EXISTS`); extend `persistence/writer.py` to persist `Incident` rows and
   `QualityEvent.threshold_details` in the same transaction as everything else.
2. New `sentinel/observability/` package: `views.py` (read models), `health.py` (pure
   Dataset-Health and Recurring-Failure derivation), `queries.py` (`ObservabilityQueryService`).
3. Deterministic shared test fixture builder (Part 9's scenario list).
4. Unit tests: schema/writer additions, `ObservabilityQueryService` (all six views + filtering +
   time windows), `health.py`'s pure functions.
5. Integration test: full validate → persist → query flow.
6. Presentation layer per your Part 11 decision — either `dashboard/app.py` (Streamlit) or new
   `sentinel dashboard` CLI command(s) — reading only through `ObservabilityQueryService`.
7. Manual verification checklist for the presentation layer (documented, not automated).
8. Engineering documentation: this file's Phase B addendum (What Was Built, Engineering Analysis,
   Verification, Definition of Done) + README status line update, matching Milestones 4/5's
   pattern.
9. Full test suite + lint sweep.

Stopping here per the milestone's own instructions — awaiting your decisions on Part 11 (or,
as with Milestone 5, feel free to say "go with your recommendations" and I'll proceed with the
choices marked recommended above).

---

# Milestone 6 — Phase B: What Was Built, Verified, and Left Open

You approved all five Part 11 recommendations verbatim ("go with your recommendations"): Streamlit
over the CLI, the slim `incidents` shape, no backfill, the Dataset Health/Recurring Failure
semantics as proposed, and the time window not applying to Dataset Health. Everything below
implements those five decisions.

## Part 13 — What Was Built

**Schema (`persistence/schema.py`):** a new `incidents` table, exactly the slim shape from Part 4
(`priority`/`score` as real columns, `components`/`reasons` as JSON, no `created_at`), added as a
second `CREATE TABLE IF NOT EXISTS` statement. A separate `_COLUMN_ADDITIONS` pass runs
`ALTER TABLE quality_events ADD COLUMN IF NOT EXISTS details VARCHAR` — a distinct statement list
from `_STATEMENTS`, because `ADD COLUMN` needs different idempotency handling than `CREATE TABLE`
(the latter no-ops against a table that already exists in any shape; the former is what actually
reaches an existing `quality_events` table and adds the column it's missing). `ensure_schema()`
now runs both passes, in order, every time — same "safe on a brand-new store and an existing one"
guarantee the four original tables already had.

**Persistence (`mapping.py`, `writer.py`):** `IncidentRow` (a new frozen dataclass) and
`QualityEventRow.details` (a new field) carry the two previously-deferred facts through
`to_rows()`. The one piece of real logic here: matching each `Incident` back to the `QualityEvent`
row it belongs to. `Incident` doesn't carry a foreign key — it holds a reference to the actual
`QualityEvent` object it was computed from — so `to_rows()` builds a `dict[int, uuid.UUID]` keyed
by `id(event)` while it's generating each event's row UUID, then looks that identity up when it
gets to the matching `Incident`. Identity (not position or value equality) is the correct match key
here for the same reason `cli/main.py`'s existing `_incident_for()` already uses identity — two
`QualityEvent`s can be equal-by-value but are never the same event twice in one run. `writer.py`
inserts both new pieces inside the same transaction `persist_validation_run()` already runs, so a
run's incidents and threshold details are never partially persisted relative to its events.

**`sentinel/observability/` (new package):**
- `views.py` (125 lines) — the six frozen-dataclass read models plus `DatasetHealth` and
  `RecurrenceClassification` enums.
- `health.py` (94 lines, no `duckdb` import) — `derive_dataset_health()` and
  `classify_recurrence()`, pure functions over already-fetched values, exactly as designed.
- `queries.py` (488 lines) — `ObservabilityQueryService`, one method per required view, plus
  `rule_names_for_dataset()`. That last method wasn't in the Phase A design — it surfaced during
  dashboard implementation as the glue the Metric Trends selector needs ("which rules has this
  dataset ever had, so the dropdown has something to show") and follows the same bounded-query
  discipline as everything else (`SELECT DISTINCT ... ORDER BY`, no loop).
- `__init__.py` — re-exports `views.py`/`health.py` names only. `ObservabilityQueryService` and
  `TimeWindow` are deliberately **not** re-exported here (Part 14 explains why); callers import
  them directly from `sentinel.observability.queries`.

**Dashboard (`dashboard/app.py`, 209 lines):** the Streamlit app from Part 8, Option B. One file,
no business logic — every number on the page comes from an `ObservabilityQueryService` call.
Sidebar: a Time Window selectbox (default "Last 7 days") and a dataset drill-down selectbox.
Sections, in order: Dataset Health (a table across all datasets, with a colored-glyph health
indicator), Recent Incidents, Failed Rules, Recurring Failures (with an explanatory caption of what
the three classifications mean), and — only once a specific dataset is selected — Metric Trends
(a rule-name selector feeding a line chart, with an expander showing the latest point's raw
`threshold_details` JSON) and Quality History. Per Part 9, this file has no automated test; Part 16
below is its manual verification.

**Dependencies (`pyproject.toml`):** a new `dashboard = ["streamlit>=1.35"]` group, kept separate
from `dependencies` and `dev` for the reason stated in Part 8 — `sentinel validate`/`sentinel
history` users install a web framework only if they also want the dashboard.

## Part 14 — Decisions Made During Implementation

Two things came up that Phase A didn't anticipate, both resolved in favor of testability without
changing the approved design:

**The `__init__.py` re-export had to be narrowed.** The first draft of
`sentinel/observability/__init__.py` re-exported `ObservabilityQueryService` and `TimeWindow`
alongside the `views.py`/`health.py` names, for a flat, convenient import surface. That broke
`health.py`'s own design goal: importing `sentinel.observability` at all (even just to reach
`health.py`'s pure functions) transitively imported `queries.py`, which imports `duckdb` —
meaning `test_health.py` could no longer be collected without `duckdb` installed, defeating the
entire point of keeping health-derivation logic duckdb-free. Fixed by re-exporting only the
`views.py`/`health.py` names; `ObservabilityQueryService` is imported directly from
`sentinel.observability.queries`. This isn't a workaround — it matches the precedent already set by
`sentinel.persistence`: `DuckDBHistoricalMetricsSource` and `DuckDBFailureHistorySource` are never
re-exported through `persistence/__init__.py` either, for the identical reason.

**`rule_names_for_dataset()` was added mid-implementation**, once the dashboard's Metric Trends
section needed a way to populate its rule selector. It wasn't in the Phase A method list because
Phase A designed the six required views, not the dashboard's own UI plumbing — this one exists
purely to answer "what can I even put in this dropdown," and was tested the same way as every
other query (real DuckDB, including the empty-dataset case).

No other deviations from the approved Part 4/5/6/7/8 design. The five Part 11 answers were
implemented exactly as recommended, not as a default to fall back on if something else proved
harder — none of them did.

## Part 15 — Verification

Same discipline as every prior milestone: syntax-checked and lint-checked in full, executed for
real wherever the sandbox's missing dependencies allow, and every gap disclosed rather than
glossed over.

**Static checks — clean, full tree:** `python3 -m py_compile` on every `.py` file under `src/`,
`tests/`, and `dashboard/` — zero errors. A 100-character line-length sweep — zero violations.
`ruff check src tests dashboard` — zero findings in anything this milestone touched. Two findings
remain in the whole tree, both in files this milestone did not modify and both confirmed
pre-existing by running `ruff` on each file in isolation:
`src/sentinel/registration.py` (an `I001` import-order nit, present since Milestone 5) and
`tests/unit/datasources/test_duckdb_source.py` (an unused `datetime.UTC` import, present since
Milestone 2/3). Neither is new, neither is mine to fix under this milestone's scope, and both are
disclosed here rather than silently left out of the report.

**Real test execution:** this sandbox has no network access and cannot install `duckdb`, `typer`,
`psycopg`, or `pytest` (confirmed again this session: `pip install duckdb` still fails with
"No matching distribution found"). Real `pytest` is therefore unavailable, so — as in Milestones
4 and 5 — a small hand-rolled shim (faking just enough of `pytest`'s surface: `raises`, `approx`,
`skip`, `fixture`/`autouse`, `mark.parametrize`, `MonkeyPatch`, and the `tmp_path` fixture)
discovers and actually executes every `test_*` function. Result, across the entire suite:

```
PASSED:  311
FAILED:  0
SKIPPED (module could not be imported — needs duckdb/typer/psycopg): 10 modules
SKIPPED (hit the same gap at call time, e.g. register_all() touching duckdb_source): 6 tests
```

**This is a materially larger disclosed gap than Milestones 4 or 5**, which each had a single
unexecutable query. Milestone 6's entire `ObservabilityQueryService` — all six required views plus
`rule_names_for_dataset()`, roughly fifteen distinct SQL statements including three
window-function queries — and both schema migrations could not be run for real in any environment
available this session, because every one of them needs a live `duckdb` connection. The ten
unexecutable modules are `test_queries.py` (the query-layer's own unit tests), `test_engine.py`,
`test_history.py`, `test_schema.py`, `test_writer.py` (all of `persistence/`'s test suite),
`test_duckdb_source.py`, `test_postgres_source.py`, `test_cli.py`, `test_postgres_duckdb_parity.py`,
and `test_observability_end_to_end.py` (the milestone's own required end-to-end test). Every one of
these was verified instead by careful hand-tracing against the deterministic fixture in
`tests/unit/observability/fixtures.py` — each expected count, ordering, and classification in
`test_queries.py` was computed by hand against `AS_OF` and the fixture's exact timestamps, not
guessed — but hand-tracing is not the same claim as a green test run, and this report says so
plainly rather than implying otherwise.

What *did* execute for real, and passed: `test_health.py`'s fourteen cases (pure functions, no
`duckdb` dependency — this is exactly why Part 14's `__init__.py` fix mattered), every rule/domain/
threshold/prioritization/orchestration/config-loading/policy-loading/dataset-loading test already
covered by Milestones 0-5, and the parts of `test_registration.py`/`test_end_to_end.py` that don't
call `register_all()` (the calls that do reach `duckdb_source.py`'s `import duckdb` and are counted
above as environment-gap skips, not failures — they are not code defects, they are this sandbox
missing a package it cannot download).

**The dashboard itself could not be executed at all** — no Streamlit runtime exists in this
session, on either side of the device bridge. `dashboard/app.py` was verified by `py_compile`, the
line-length sweep, `ruff`, and a structural read-through confirming it makes no call that bypasses
`ObservabilityQueryService` (no raw SQL, no import of `duckdb` itself). Part 16 is the checklist for
running it for real on your machine, where `uv sync --group dashboard` can actually reach PyPI.

## Part 16 — Manual Dashboard Smoke-Test Checklist

Run once, locally, after `uv sync --group dashboard`:

```
uv run streamlit run dashboard/app.py
```

1. Page loads without a traceback; title and "as of <timestamp>" caption render.
2. Sidebar Time Window defaults to "Last 7 days"; switching to "Last 24 hours" / "Last 30 days"
   changes the Recent Incidents / Failed Rules / Recurring Failures / Metric Trends / Quality
   History rows, but the Dataset Health table does **not** change (Part 11, Q5) — confirms the
   window control is correctly wired to skip that one view.
3. Dataset Health shows one row per dataset that has ever been validated, each with a colored
   health glyph consistent with its latest run's status and incident priority.
4. Selecting a dataset in the sidebar reveals Metric Trends and Quality History; selecting
   "(all datasets)" hides both, without an error.
5. In Metric Trends, picking a rule name shows a line chart with at least one point, and the
   expander below it shows non-empty `threshold_details` JSON for at least one static-strategy
   rule (the Milestone 5 `details` field surviving persistence).
6. Recurring Failures' three classifications (first occurrence / recurring / persistent) each
   appear for at least one dataset+rule pair, assuming `sentinel validate` has been run enough
   times locally to produce that history — and the caption explaining the three terms is legible
   without needing this document open alongside it.
7. No console error in the terminal running `streamlit run` after clicking through every sidebar
   control at least once.

## Part 17 — Definition of Done

- [x] All six required views implemented, each backed by `ObservabilityQueryService`, none
      recomputing validation/threshold/prioritization logic.
- [x] Dashboard technology chosen and justified (Part 8); implemented as a single
      `dashboard/app.py` with zero business logic.
- [x] Query layer avoids N+1 (window-function + bounded IN-list queries throughout; Part 5/15).
- [x] Read models are a separate `views.py`, never domain objects reused as DTOs.
- [x] Deterministic fixtures covering healthy / occasional / recurring / persistent / WARNING /
      HIGH / CRITICAL / never-validated scenarios (`tests/unit/observability/fixtures.py`).
- [x] Unit tests per view, filtering tests, one true end-to-end integration test — all written;
      hand-verified rather than executed, per Part 15's disclosed gap.
- [x] Manual smoke-test checklist provided in lieu of automated dashboard tests (Part 16).
- [x] Two additive, backward-compatible schema changes, both idempotent on a pre-existing store.
- [x] Explicitly out-of-scope items (Part 10) left untouched.
- [x] Engineering documentation (this addendum) and `README.md` updated.
