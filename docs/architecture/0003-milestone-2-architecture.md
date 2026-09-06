# Sentinel — Milestone 2 Architecture

**Status:** Approved 2026-08-26 — see Part 9 for the task list this now unblocks
**Scope:** Milestone 2 (CLI & Persistence) — `sentinel validate`, `sentinel history`, and durable storage of Validation Runs, Metrics, and Quality Events, without changing anything about how Rules, Threshold Strategies, or the Orchestrator work.

---

## Part 1 — What This Milestone Actually Needs

The PRD's own roadmap (section 13) puts "dataset registry" in *Phase 2 — Platformization*, after *Phase 1 — Core MVP* (CLI + persistence, which is this milestone). So a full dataset-registration workflow — CRUD, versioning, an API surface for managing datasets — is out of scope here by the PRD's own phasing, not just by the "avoid repository abstractions" constraint. That resolves one question before it needs asking: dataset and policy resolution for this milestone stays filesystem convention, not a database-backed registry.

The PRD's data-model sketch (section 11) lists six entities; this milestone needs four. `policies` is skipped — policy versioning is explicitly Phase 2, and `ValidationRun.policy_version` already stays a string snapshot from the loaded YAML, unchanged since Milestone 0. `incidents` is Milestone 5. What's left — `datasets`, `validation_runs`, `metrics`, `quality_events` — is exactly what FR-01, FR-06, FR-07, and FR-08 ask this milestone to persist.

---

## Part 2 — DataSource: DuckDB, Pulled Forward From Milestone 3

No `DataSource` implementation exists yet — `Project_Milestones.md` slots the DuckDB adapter into Milestone 3. But `sentinel validate orders` has nothing to read rows from without one, so this milestone needs *a* working adapter to be more than a CLI that always errors.

The original plan here was a hand-rolled CSV reader, reasoned as "don't preempt Milestone 3's named deliverable." That reasoning didn't hold up: DuckDB can query a CSV file directly (`SELECT count(*) FROM read_csv_auto(path)`, `count(distinct col)`, `MAX(col)`, and so on), which is *less* code than hand-rolling `row_count`/`null_count`/`distinct_count`/`max_value` as Python loops over an in-memory row list — and it's the actual technology the PRD names for this role ("DuckDB: local analytics and fast MVP experimentation"), not a stand-in that gets deleted the moment Milestone 3 starts.

`datasources/duckdb_source.py: DuckDBSource` — `source_type = "duckdb"` — takes `Dataset.config_reference` as a path to one CSV file and answers each `DataSource` method with one DuckDB aggregate query against `read_csv_auto(config_reference)`. This is deliberately narrow: single local file, no schema introspection, no multi-table support. Milestone 3's actual adapter deliverable is still real work on top of this — freshness/schema-validation rules need schema introspection this doesn't have, and a real warehouse-backed dataset needs more than a local file path — this just means Milestone 3 extends an existing `duckdb_source.py` rather than writing one from scratch.

This connection is intentionally ephemeral — opened fresh per `sentinel validate` invocation, never persisted, no relationship to the history store below beyond both happening to use DuckDB as the query engine.

---

## Part 3 — Persistence: DuckDB Now, SQLAlchemy + Postgres Later

The original brief called for SQLAlchemy + PostgreSQL + Alembic. That's still the right long-term choice for the reasons laid out in Part 3a below — but for this milestone, persistence uses DuckDB too: a second, *separate* embedded database file (`SENTINEL_DB_PATH`, defaulting to `./sentinel.duckdb`) storing the four tables, written to directly via the `duckdb` Python API's parameterized `execute()`, with schema creation as idempotent `CREATE TABLE IF NOT EXISTS` DDL run once at startup — no Alembic yet, since there's no meaningful migration history to manage over four tables that don't exist anywhere yet.

**This is a real trade-off, not a free simplification, and it's worth being explicit about why it's fine for now and what it defers.** DuckDB's own documentation is clear that concurrent writes to the same file from multiple processes aren't safely supported the way Postgres's MVCC handles concurrent writers — fine for a single local user running `sentinel validate` sequentially, not fine the moment multiple pipelines or a scheduled job might write history at the same time, and not fine for the FastAPI service the PRD's roadmap eventually adds (which would need to read this same history concurrently with writers). That's exactly the boundary where this needs to become Postgres — not "eventually, someday," but at the specific moment concurrent access becomes real. Keeping the persistence code confined to `persistence/`'s own module boundary (below) is what keeps that swap a contained rewrite of a handful of files rather than something that touches the CLI or domain layers.

**Two separate DuckDB databases, not one doing double duty:** `DuckDBSource` (Part 2) and the persistence store are unrelated connections to unrelated files, serving unrelated roles — one is a transient analytical query against the dataset being validated, the other is a durable operational log of what happened. Using the same underlying engine for both was a scope simplification for this milestone, not a design coupling; nothing about swapping the persistence side to Postgres later touches `DuckDBSource` at all.

---

## Part 4 — Schema

Four tables, matching the M1-era `ValidationRun`/`Metric`/`QualityEvent` composition directly rather than inventing new normalization:

```
datasets            id (varchar, PK), name, source_type, environment, owner,
                     criticality, config_reference

validation_runs     id (uuid, PK), dataset_id (FK -> datasets.id),
                     policy_version, started_at, finished_at, status

metrics             id (uuid, PK), validation_run_id (FK -> validation_runs.id),
                     metric_name, value, computed_at

quality_events       id (uuid, PK), validation_run_id (FK -> validation_runs.id),
                     metric_id (FK -> metrics.id), status, expected,
                     strategy_type, severity, blocking
```

`datasets.id` reuses the domain `Dataset.id` (a human-assigned string per FR-01) as its own primary key. The other three get `uuid.uuid4()`-generated primary keys, assigned in Python at mapping time rather than left to a DB-side default — that's what lets `sentinel validate` print `Run ID: <uuid>` immediately after persisting, no read-back required. DuckDB has a native `UUID` column type, used directly.

`metrics` is its own table, not columns folded into `quality_events`, because it mirrors a relationship that already exists in the domain model (`QualityEvent.metric: Metric`) rather than adding new structure — and it's what FR-08 ("retain metric history... for future adaptive thresholds") and the already-present-but-unused `ThresholdStrategy.evaluate(..., history: Sequence[Metric])` parameter will want to query directly once Milestone 4 needs metric history independent of any one run's verdict.

`status`, `severity`, and `strategy_type` are plain strings, not DuckDB `ENUM` types — widening an enum type later is more friction than a string column ever is, for no benefit at this scale.

No JSONB/JSON column this milestone. Nothing currently reads flexible metadata back, policies aren't versioned/persisted yet, and the human-readable `expected` string already records what was checked. Revisit if a real reproducibility need shows up.

---

## Part 5 — Domain ↔ Persistence Mapping

One direction only. `persistence/mapping.py: to_rows(run) -> PersistableRun` (a small plain container of the four kinds of row-tuples/dicts ready for parameterized `INSERT`) — a pure function that imports domain types. It takes only a `ValidationRun`, not a separate `Dataset` argument alongside it: `ValidationRun.dataset` already carries the full object (Milestone 0's own choice, so the orchestrator's result is self-contained), and accepting a second `dataset` parameter here would just be a second place a caller could pass a mismatched one — discovered while implementing this, not part of the original sketch. Nothing in `domain/`, `rules/`, `thresholds/`, or `orchestration/` ever imports `persistence`, matching the one-way dependency rule Milestone 0 already established for its own package boundaries.

The read path (`history`) does not reconstruct `ValidationRun`/`QualityEvent` domain objects from stored rows — it only needs a thin projection (run id, started_at, status, and each event's rule name + status) to display a summary. Building a full row→domain mapper would solve a problem nothing asks for yet.

---

## Part 6 — Persistence Module Shape

```
src/sentinel/persistence/
    engine.py     # get_connection() -> duckdb.DuckDBPyConnection, from SENTINEL_DB_PATH
    schema.py     # ensure_schema(conn) -> None; idempotent CREATE TABLE IF NOT EXISTS
    mapping.py    # to_rows(run) -> PersistableRun (one direction; run.dataset is used directly)
    writer.py     # persist_validation_run(conn, run) -> UUID
    reader.py     # list_recent_runs(conn, dataset_name, limit) -> list[RunSummary]
```

No `Repository` base class, no generic `.save()/.get()`. `writer.py` and `reader.py` each expose exactly one function shaped around what the two CLI commands need — there's no second caller yet to justify a shared interface, and adding one now would be exactly the kind of premature abstraction the brief asks to avoid.

---

## Part 7 — DataSource Registry

`Project_Milestones.md` and Milestone 0's own notes left this an open question ("worth deciding in Milestone 1 whether DataSource needs a registry too... since no concrete adapter exists yet"). With `DuckDBSource` landing now and a second adapter (a richer DuckDB/warehouse story) confirmed for Milestone 3, the answer is yes — a `datasources/registry.py` mirroring `rules/registry.py` and `thresholds/registry.py` exactly: a dict keyed by `source_type`, a `@register_data_source` decorator, `get_data_source(source_type, config_reference)`. `register_all()` (Milestone 1) grows to cover it, and its docstring is updated to describe bootstrapping all three registries rather than just rules and thresholds.

---

## Part 8 — CLI

**Dataset and policy resolution**, filesystem convention (Part 1):

```
datasets/orders.yaml   # id, name, source_type: duckdb, environment, owner, criticality,
                       # config_reference: data/orders.csv
policies/orders.yaml   # the existing Policy schema, unchanged
data/orders.csv        # real sample data for local CLI use
```

resolved via `SENTINEL_DATASETS_DIR` / `SENTINEL_POLICIES_DIR` env vars, defaulting to `datasets/` / `policies/` relative to the working directory.

**Composition root:** `cli/bootstrap.py: build_context() -> AppContext`, a plain frozen dataclass holding the persistence connection. It calls `register_all()` and calls `ensure_schema()` once. No DI framework — called once per CLI invocation, passed as a plain argument to whichever command needs it.

**`sentinel validate <dataset>`:** resolve dataset + policy from the filesystem convention above, build a `DuckDBSource` from `config_reference`, run the existing `ValidationOrchestrator` unchanged, persist the result, print the summary (dataset, run id, headline status, one ✓/✗ line per rule), exit with a status derived from `blocking`:

- exit `0` — no blocking event is FAIL, and nothing WARNs.
- exit `1` — something WARNs, but no blocking event FAILs.
- exit `2` — a blocking event FAILs.

This resolves the question Milestone 0 explicitly deferred here (`QualityEvent.blocking` "deliberately NOT folded into `ValidationRun.status` aggregation — that's a Milestone 2 CLI decision"): `ValidationRun.status` stays the raw worst-status-wins fact Milestone 0 built; the exit code and headline verdict are a separate, blocking-aware judgment the CLI makes on top of it. The per-rule ✓/✗ line always shows every rule's real status regardless of `blocking`.

**`sentinel history <dataset> [--limit N]`:** query `persistence/reader.py` for recent runs against that dataset name, default limit (10), display timestamp, status, and which rule(s) failed if any — no full domain reconstruction, per Part 5.

---

## Part 9 — Task Breakdown

Ordered by dependency:

1. `persistence/engine.py` (`SENTINEL_DB_PATH` connection) + `persistence/schema.py` (the four tables).
2. `datasources/registry.py` (mirroring rules/thresholds) + `datasources/duckdb_source.py` + `register_all()` updated to cover it.
3. `persistence/mapping.py` (`to_rows`) + `persistence/writer.py`.
4. Dataset/policy directory resolution (env vars + defaults) + the real `datasets/orders.yaml`, `policies/orders.yaml`, `data/orders.csv` files.
5. `cli/bootstrap.py` (`build_context`) + `cli/main.py` with `sentinel validate` — blocking-aware exit code, ✓/✗ summary.
6. `persistence/reader.py` + `sentinel history`.
7. Integration tests: `validate` end-to-end against a real (temp-file) DuckDB history store + the real `DuckDBSource` against the real CSV fixture; `history` against runs it wrote.
8. Full suite + ruff + mypy, close-out.

---

## Decisions Log

- **Dataset/policy registration stays filesystem convention**, not a database-backed registry — the PRD's own roadmap places a real dataset registry in Phase 2, after this milestone.
- **`policies` and `incidents` are not persisted this milestone** — policy versioning and incidents are later-phase concerns; `ValidationRun.policy_version` stays a string snapshot.
- **`DuckDBSource` (not a hand-rolled CSV reader) is the Milestone 2 DataSource adapter**, pulled forward from Milestone 3's slot but scoped narrowly (single local file, no schema introspection) — Milestone 3 extends this rather than replacing it.
- **Persistence uses DuckDB for now, not SQLAlchemy + PostgreSQL** — a deliberate, named trade-off, revisited once concurrent writers (multiple pipelines, or the PRD's future API layer) become real, not "eventually." The persistence module boundary (Part 6) is what keeps that swap contained.
- **Two separate DuckDB databases** — `DuckDBSource`'s ephemeral per-invocation query connection, and the persistence store's durable file — serving unrelated roles, not one file doing double duty.
- **Four tables** (`datasets`, `validation_runs`, `metrics`, `quality_events`), `metrics` kept separate from `quality_events` as a direct mirror of the existing `QualityEvent.metric` composition, not new normalization.
- **No JSONB/JSON this milestone** — nothing reads flexible metadata back yet.
- **`DataSource` gets a registry**, mirroring `Rule`/`ThresholdStrategy` — resolves the question Milestone 0 left open once a second adapter became concrete.
- **CLI exit code is blocking-aware**, not a direct mirror of `ValidationRun.status` — resolves the question Milestone 0 explicitly deferred to this milestone.
- **Domain → persistence mapping is one-directional** — `history` reads a thin projection, not a reconstructed domain object graph.
- **No `Repository` abstraction** — `writer.py`/`reader.py` expose one function each, shaped around the two CLI commands' actual needs.

The architecture is approved. Starting on Part 9's task list.
