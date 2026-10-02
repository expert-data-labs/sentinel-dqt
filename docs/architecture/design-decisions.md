# Design Decisions

This page records the decisions that shape Sentinel, the alternatives that were considered, and the conditions under which each decision should be revisited. Component-level details live in the [component reference](../README.md#components).

Each entry follows the same structure: **Decision**, **Why**, **Alternatives considered**, **Trade-off**, **Revisit when**.

---

## Modelling

### D1. Definitions and facts are separate kinds of object

- **Decision.** Config-time definitions (`Policy`, `RuleConfig`, `ThresholdConfig`, `Dataset`) are kept apart from runtime facts (`Metric`, `ThresholdResult`, `QualityEvent`, `ValidationRun`, `Incident`).
- **Why.** Definitions change when people edit YAML. Facts are a historical record and must never change. Mixing them makes history depend on whatever config happened to be loaded.
- **Trade-off.** More types than a single "check result" object.

### D2. Measurement is separate from judgement

- **Decision.** A Rule returns a `Metric` (a number). A Threshold Strategy returns a `ThresholdResult` (a verdict). A `QualityEvent` holds both and adds the policy's severity and blocking flag. The persisted schema keeps them in separate tables (`metrics`, `quality_events`).
- **Why.** Adaptive strategies need past *values*. Re-judging history under a new threshold needs raw values. Rules and strategies become independently testable.
- **Alternatives considered.** One wide `quality_events` row with `actual`, `expected` and `status` columns. Rejected as the storage *shape* of the domain; the flat view is exposed instead as read-only properties on `QualityEvent`.
- **Trade-off.** One extra join on most history queries.

### D3. Pydantic at the input boundary, frozen dataclasses for facts

- **Decision.** Definitions are frozen pydantic models because they come from human-edited YAML and must be validated. Facts are frozen dataclasses because Sentinel creates them itself and they only need immutability.
- **Trade-off.** Two modelling libraries in one domain package.

### D4. Run status and pipeline exit code are different judgements

- **Decision.** `ValidationRun.status` is the worst status across all events and ignores the `blocking` flag. The CLI derives the exit code separately and does honour `blocking`.
- **Why.** The run status answers "was the data good?", a fact that must stay comparable across time. The exit code answers "should the pipeline stop?", a policy decision that can change. If `blocking` influenced the stored status, flipping a rule from blocking to non-blocking would make identical data look different in history.
- **Trade-off.** A run can be stored as FAIL while the pipeline continued with exit code 0. The CLI summary always shows every rule's true status, which keeps this visible.

### D5. Structured extras are JSON strings, not nested objects

- **Decision.** `Metric.details` and `ThresholdResult.details` are `str | None` holding JSON.
- **Why.** A string is immutable by type, so frozen dataclasses stay frozen without a frozen-mapping wrapper. It is also directly persistable.
- **Trade-off.** Consumers must `json.loads()` and know each strategy's keys. `prioritization/deviation.py` and `confidence.py` do exactly that.

---

## Extensibility

### D6. Plug-ins are Protocols resolved through a registry

- **Decision.** `Rule`, `ThresholdStrategy` and `DataSource` are `typing.Protocol`s. Implementations register under a string key with a decorator. Lookup is a dict access.
- **Why.** "Add a rule" means "add a file", with no central `if/elif` to edit. Protocols need no inheritance and are easy to fake in tests.
- **Alternatives considered.** Plain functions with an `if rule.type == ...` dispatch (less code for three rules, but every new type edits a central branch and nothing can be substituted in tests); an ABC hierarchy (heavier, adds nothing a Protocol doesn't); a plugin framework with entry points (unnecessary while all implementations ship in this package).
- **Trade-off.** Registries are global module state.
- **Revisit when.** Third-party packages need to contribute rules. Entry-point discovery would then replace `register_all()`.

### D7. Registration is an explicit function call

- **Decision.** `sentinel.registration.register_all()` imports every concrete module so their decorators run. Every entry point calls it once.
- **Why.** Decorators only fire on import, and nothing else imports `rules/null_rate.py`. Making registration a visible call is clearer than relying on package import order.
- **Trade-off.** A new implementation must also be added to `register_all()`.

### D8. `DataSource` exposes capabilities, not `execute(sql)`

- **Decision.** The interface is a handful of aggregate questions: `row_count`, `null_count`, `distinct_count`, `max_value`, `columns`.
- **Why.** A generic query method would leak SQL dialects into every rule, and a rule could no longer run unchanged against a different backend.
- **Trade-off.** The interface grows by one method whenever a genuinely new *kind* of measurement is needed (`columns()` was added for schema validation). Each method is a separate query against the source.
- **Revisit when.** Scan cost on large tables dominates. A batched "profile" method could compute several aggregates in one pass without giving up backend independence.

### D9. Coordinators are concrete classes

- **Decision.** `ValidationOrchestrator`, `IncidentPrioritizer` and `ObservabilityQueryService` are plain classes with no Protocol or registry.
- **Why.** Each has exactly one algorithm. Nothing selects between implementations by config string, so an interface would be indirection without payoff.
- **Revisit when.** A second implementation legitimately appears, for example a parallel orchestrator. Extracting a Protocol then is a small, additive change.

---

## Thresholds and history

### D10. Strategies receive history; they never fetch it

- **Decision.** `ThresholdStrategy.evaluate(metric, config, history)` receives past Metrics as a plain sequence. The orchestrator fetches them through an injected `HistoricalMetricsSource`.
- **Why.** Strategies stay pure functions that can be tested with a list of numbers and no database. It mirrors how `DataSource` keeps rules ignorant of storage.
- **Trade-off.** The orchestrator fetches history for every rule, including static ones that ignore it. This keeps the orchestrator free of strategy-specific branches.

### D11. History is keyed by `(dataset_id, rule name)` and capped

- **Decision.** History lookups filter on the dataset id and the rule's `name` from the policy, newest first, capped at 90 rows by default.
- **Why.** Two `null_rate` rules on different columns get independent histories. The cap bounds the cost of every run on a long-lived dataset.
- **Trade-off.** Renaming a rule in YAML starts its history over. Policy version is ignored for history lookup.

### D12. "Not enough history" is a separate error from "bad config"

- **Decision.** `InsufficientHistoryError` is distinct from `ThresholdConfigError`.
- **Why.** One means "fix your YAML", the other means "run a few more times". Conflating them would send people to fix a policy that is not broken.
- **Known gap.** Nothing in the run path catches `InsufficientHistoryError` yet, so a brand-new rule configured with an adaptive strategy aborts the run. See [Threshold Strategies](../components/thresholds.md#cold-start).

---

## Prioritization and observability

### D13. Prioritization is a deterministic weighted score

- **Decision.** Five components (severity, dataset criticality, deviation, failure frequency, anomaly confidence) are scored 0–100 and combined with fixed weights into a single score, then bucketed into INFO, WARNING, HIGH or CRITICAL. Every Incident carries its components and five human-readable reasons.
- **Why.** Every priority can be explained line by line. No training data is needed.
- **Alternatives considered.** An ML ranking model (opaque, needs labelled incidents); a single severity field (cannot tell a first-time blip from a fifth consecutive failure).
- **Revisit when.** Enough labelled incident outcomes exist to tune weights from data.

### D14. Incidents are a separate object, produced after the event

- **Decision.** `IncidentPrioritizer` runs after a `QualityEvent` is built and produces a new `Incident` that references it. Rules and strategies know nothing about prioritization.
- **Why.** "What did we observe", "is it anomalous" and "how much does it matter" are three different questions. Prioritization also needs inputs no rule or strategy has: dataset criticality and failure history.

### D15. Dataset health derives from incident priority, not raw status

- **Decision.** UNKNOWN (never validated), HEALTHY (latest run has no incidents), DEGRADED (highest incident priority below CRITICAL), CRITICAL. Computed at read time from the latest run; never stored.
- **Why.** Using raw FAIL would flatten exactly the distinctions prioritization exists to make. UNKNOWN is kept separate because "never checked" is not the same claim as "checked and passed".

### D16. Two different windows for "repeated failure"

- **Decision.** The prioritizer counts failures over the last *N evaluations* (row-count window). The Recurring Failures view counts failures within a *calendar window* (24h, 7d or 30d).
- **Why.** They answer different questions: "how much precedent does this failure have right now" versus "what has kept breaking this week". Reusing one for the other would silently change its meaning.

### D17. Read-side queries take an explicit `as_of`

- **Decision.** Every windowed method on `ObservabilityQueryService` takes `as_of: datetime` instead of calling `now()` internally.
- **Why.** Tests pass a fixed timestamp and are deterministic.

---

## Storage and operation

### D18. Sentinel's own store is PostgreSQL

- **Decision.** Runs, metrics, events and incidents are written to a shared PostgreSQL database (`SENTINEL_DATABASE_URL`) through psycopg 3 with hand-written, parameterized SQL. No ORM.
- **Why.** Sentinel must serve many teams and simultaneous validation runs (CLI processes now, API workers next). Postgres gives concurrent writers, row-level locking, advisory locks for coordination, constraints, and a managed-service path in every cloud. It was already a supported data source, so no new technology was added.
- **History.** The store started as an embedded DuckDB file: zero setup, but one writing process per file. It was replaced once concurrent, multi-team use became a requirement.
- **Alternatives considered.** Keeping DuckDB for local use behind a store interface (two SQL dialects to maintain and test). MySQL (no advantage here, and a new technology). SQLAlchemy ORM (more abstraction than a five-table, write-once schema needs).
- **Trade-off.** Local development and the store tests need a running Postgres (`docker compose up -d`).
- **Revisit when.** Analytical reads over long history get slow: add partitioning by `started_at` or replicate to a warehouse, keeping Postgres as the system of record.

### D19. The data being validated and Sentinel's store are unrelated connections

- **Decision.** `DuckDBSource` opens its own in-memory DuckDB connection per run to query a CSV file. The history store is a separate, durable file.
- **Why.** They serve unrelated roles. Moving the history store from DuckDB to Postgres did not touch `DuckDBSource` at all.

### D20. Persistence is one-directional, with no repository layer

- **Decision.** `persistence/mapping.py::to_rows()` flattens a `ValidationRun` into rows and assigns UUIDs. `writer.py` writes them in one transaction. Read paths return thin projections, never reconstructed domain objects.
- **Why.** Nothing needs a full row-to-domain mapper. One transaction guarantees no reader ever sees half a run.

### D21. Versioned migrations with Alembic, in raw SQL

- **Decision.** Schema changes are Alembic migrations whose bodies are plain SQL (`op.execute`). `sentinel db upgrade` applies them once per deploy; the CLI refuses to run (exit `3`) if the store isn't at the code's head revision.
- **Why.** A shared production database needs ordered, reviewable, reversible changes, applied once rather than by every process at startup. Raw SQL keeps migrations readable without introducing ORM models.
- **Alternatives considered.** Idempotent DDL on every start (the previous approach; can't express destructive or data changes, and races between processes). Numbered SQL files with a custom runner (no dependency, but reinvents version tracking and locking).
- **Trade-off.** Adds `alembic` and `sqlalchemy` (used only as Alembic's driver).

### D22. Filesystem convention instead of a dataset registry

- **Decision.** `sentinel validate orders` reads `datasets/orders.yaml` and `policies/orders.yaml`. Directories are overridable with `SENTINEL_DATASETS_DIR` and `SENTINEL_POLICIES_DIR`.
- **Why.** Config lives next to code in version control, which gives review and history for free.
- **Revisit when.** Datasets are registered by teams that don't share a repository, or policies need server-side versioning.

### D23. Connection details travel in `config_reference`, secrets through `${ENV_VAR}`

- **Decision.** A database dataset's `config_reference` is a connection URL with the object as a query parameter (`?table=orders`, `?collection=orders`). It may reference environment variables (`${SNOWFLAKE_PASSWORD}`), expanded only when the adapter is created.
- **Why.** One string field works for every source with no adapter-specific fields on `Dataset`. Environment variables are the lowest common denominator every scheduler, CI system and secret manager can supply, and the stored config keeps the reference, never the secret.
- **Alternatives considered.** Per-source credential fields (schema grows with every adapter). A secrets-manager integration (ties Sentinel to one vendor; can be layered on later as another expansion syntax).
- **Trade-off.** URLs get long for warehouses with many options.

### D24. The dashboard is a thin, optional shell

- **Decision.** A single-file Streamlit app that reads only through `ObservabilityQueryService`, installed through its own optional dependency group.
- **Why.** All logic lives in the tested query layer. CLI users never install a web framework.
- **Alternatives considered.** A text dashboard in the CLI (no new dependency, but trend charts are far weaker as ASCII).

### D25. Runs of the same dataset are serialized with an advisory lock

- **Decision.** `validate_and_record()` holds a Postgres session-level advisory lock keyed on the dataset id from the history reads through the write. Different datasets don't block each other.
- **Why.** Adaptive thresholds and failure-frequency scoring read history before writing. Without serialization, two simultaneous runs of one dataset read the same history and each misses the other.
- **Alternatives considered.** `SERIALIZABLE` transactions (would hold a transaction open while rules query the data source, and need retry logic). A `dataset_runs` lock table (needs cleanup when a process crashes; advisory locks are released automatically). No coordination (silent lost updates).
- **Trade-off.** A second run of the same dataset waits for the first. Callers that prefer to reject can pass `wait=False`.
- **Revisit when.** Validation moves to a job queue with one consumer per dataset, which makes the lock redundant.

### D26. One SQL base class; optional drivers as extras

- **Decision.** DuckDB, Postgres, MySQL, Snowflake and BigQuery adapters share `SqlDataSource`, which implements the four aggregate capabilities with standard SQL. Each adapter provides only its connection, quoting, table reference and schema introspection. MongoDB implements the Protocol directly. Warehouse and database drivers are optional extras, imported only when a dataset uses them.
- **Why.** The capabilities are the same `COUNT`/`MAX` queries on every SQL engine, so writing them once removes duplication and makes identifier quoting consistent. Extras keep the core install small (the Snowflake and BigQuery clients are large).
- **Alternatives considered.** SQLAlchemy dialects for every engine (another abstraction layer, and Snowflake/BigQuery dialects are third-party). One package per adapter (more release overhead than five small modules justify).
- **Trade-off.** A SQL engine with unusual semantics must override the base methods.
- **Revisit when.** An adapter needs pushdown beyond these aggregates (sampling, partition filters); add it to the Protocol as a new capability.
