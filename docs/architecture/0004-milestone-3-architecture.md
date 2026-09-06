# Sentinel — Milestone 3 Architecture (Phase A — Compatibility Review)

**Status:** Implemented (2026-08-26). All five open questions are resolved (see Open Questions below); every Part 9 task is done, including cross-adapter integration tests (Task 11). One caveat carried over from Part 1: Task 1 ("verify DuckDB's actual timestamp behavior") was never empirically confirmed — the environment this implementation was built in has no network access to run DuckDB, psycopg, or pytest. The code is written to be correct under either possible DuckDB behavior (see `_as_utc` in `duckdb_source.py` and the adjacent test design in `test_duckdb_source.py`), but nothing in this repository has yet been confirmed by an actual `uv sync && pytest` run. That run — plus `ruff` and `mypy --strict` — is the one remaining step before this milestone can be considered verified, not just written.
**Scope:** Milestone 3 (Additional Rules & Adapters) — a Freshness rule, a Schema Validation rule, extending `DuckDBSource`, and a new `PostgresDataSource`, while keeping Rules ignorant of which backend they're reading from.

---

## Part 1 — What Was Inspected, and the Headline Finding

Per the brief, no implementation happened before this review. Inspected: `datasources/base.py` (the `DataSource` Protocol), `datasources/duckdb_source.py`, `datasources/registry.py`, `domain/metric.py`, `domain/policy.py` (`RuleConfig`/`ThresholdConfig`), `domain/events.py`, `rules/base.py` and all three Milestone 1 rules, `thresholds/base.py`/`static.py`, `orchestration/orchestrator.py`, `registration.py`, the real `datasets/orders.yaml` / `policies/orders.yaml` / `data/orders.csv`, and `.github/workflows/ci.yml`.

Headline finding: the `DataSource` Protocol was already built anticipating this milestone. Its own module docstring names schema introspection as the one method it expected to grow, and `max_value` exists today specifically "reserved for Milestone 3's freshness rule" — unused by any Milestone 1 rule. That's the design paying off: one new method, one docstring-contract tightening, no signature changes to anything that exists. The gaps are real but narrow, and they're not all on `DataSource` — two of the four are on `RuleConfig` and `Metric`, which the brief's own "Before implementation, determine whether the current `Metric.value` model supports structured observations cleanly" question anticipated.

---

## Part 2 — Gap Analysis Against the Five Required Capabilities

| Capability | Needed by | Status today |
|---|---|---|
| Row count | Freshness (empty-dataset check via row count is *not* actually needed — see Part 4), Row Count/Null Rate/Uniqueness (existing) | Supported — `row_count()` |
| Null rate / null count | Null Rate (existing) | Supported — `null_count(column)` |
| Duplicate count | Uniqueness (existing) | Supported — `distinct_count(column)` |
| Freshness (latest timestamp) | Freshness (new) | Supported in shape — `max_value(column)` exists but its timestamp/timezone contract has never been exercised or specified precisely |
| Schema inspection | Schema Validation (new) | **Missing** — no method returns column names or types |

Two capabilities are ready as-is (row count, null rate, duplicate count — unchanged by this milestone). One is present but under-specified (`max_value`). One is genuinely absent (schema inspection). That absence is the only place `DataSource` needs a new method.

Separately — not a `DataSource` gap, but found during the same review — `RuleConfig` cannot express the Schema Validation rule's own YAML example (`expected_schema: {...}`) at all today; it only has `column: str | None` for rule-specific config. And `Metric.value: float` cannot carry the structured missing/unexpected/mismatch differences the brief explicitly asks Schema Validation to produce. Both are addressed in Part 3.

---

## Part 3 — Proposed Interface Changes

Four changes, each scoped to the demonstrated gap it closes — nothing speculative.

### 3a. `DataSource.columns() -> dict[str, str]` (new method)

Returns every column's name mapped to a **canonical Sentinel type name**, not the backend's native type string. Canonical vocabulary, deliberately small and matching the brief's own YAML example vocabulary (`string`, `decimal`, `timestamp`) plus the obvious neighbors a real CSV/table will produce:

```
string | integer | float | decimal | boolean | timestamp | date | unknown
```

`unknown` is the escape hatch for a native type an adapter doesn't recognize — Schema Validation should be able to report "type unknown, expected decimal" as a mismatch, not crash. Each adapter owns its own native-type → canonical-type mapping internally (DuckDB's `VARCHAR`, Postgres's `text`/`character varying` both become `string`); this is exactly the "SQL dialect differences belong inside the adapters" rule from the brief, applied to types instead of queries.

Works identically for an empty dataset (0 rows): schema is structural, not data-dependent — `DESCRIBE` (DuckDB) and `information_schema.columns` (Postgres) both answer from the file/table's declared shape regardless of row count. This resolves Schema Validation's "empty dataset" edge case for free, with no special-casing in the Rule.

### 3b. Tighten `max_value`'s contract for timestamp columns (docstring only, no signature change)

Today's docstring says nothing about timezone. For Freshness to be genuinely backend-independent, both adapters must agree on what a timestamp `max_value` returns. Proposed contract: **when `column` holds timestamps, `max_value` returns a timezone-aware `datetime` in UTC.** If the underlying value has no timezone (a naive `TIMESTAMP` column, common for both DuckDB-from-CSV and Postgres's `timestamp without time zone`), the adapter attaches UTC rather than the process's local time. This is a documentation change to `datasources/base.py`, plus a real behavioral check (and fix if needed) in `DuckDBSource.max_value` — I could not verify DuckDB's actual return type for `data/orders.csv`'s `updated_at` column empirically in this session (see the note at the end of Part 6); that verification is Phase B's first task, not assumed here.

### 3c. `RuleConfig.expected_schema: dict[str, str] | None = None` (new optional field)

The Schema Validation rule's own example YAML can't be parsed by `RuleConfig` as it stands — it only carries `column` as rule-specific config. Adding one dedicated optional field mirrors exactly how `column` was already justified in `policy.py`'s docstring ("a single optional field is simpler than a discriminated union keyed by rule type, and it costs nothing today"). The alternative — generalizing `RuleConfig` to an open `params: dict[str, Any]` bag like `ThresholdConfig` — would touch every existing rule's config access pattern for one rule type's need, which is the "redesign for hypothetical futures" the brief says not to do. Being a pydantic field, malformed `expected_schema` YAML (wrong shape, non-string values) fails at policy-load time with a clear pydantic error, not partway through a validation run.

### 3d. `Metric.details: str | None = None` (new optional field)

This is the answer to the brief's explicit question. `Metric.value` stays exactly what it is today — a single float every `ThresholdStrategy` (unchanged) can evaluate — and continues to mean "the number of schema differences" for the Schema Validation rule, so `StaticThresholdStrategy` with `max: 0` works on it completely unmodified. `details` carries the structured part (which columns are missing, which are unexpected, which types mismatch) as a **JSON-encoded string**, not a nested dict or dataclass.

The string choice is deliberate, and directly answers the concern `metric.py`'s own docstring raised when a `dimensions` field was cut in Milestone 0 ("how do you keep a dict inside a frozen dataclass immutable"): a `str` is immutable by type, with no need for a frozen-mapping wrapper or a new collection type. It's also trivially serializable for the day persistence wants to store it. `QualityEvent` gets a `details` passthrough property, mirroring the existing `actual`/`expected`/`status` properties exactly — additive only; every Milestone 1 rule leaves `details` at its default `None`, and the property just forwards that.

**Named gap this leaves open:** the M2 `metrics` persistence table has no `details` column. `sentinel validate` can print structured schema differences to the console this milestone; `sentinel history` cannot show them yet. Adding that column is a schema migration, and "no new persistence architecture" is an explicit Milestone 3 constraint — so this is a deliberate, visible deferral to a later milestone, not an oversight.

---

## Part 4 — Freshness Rule

```yaml
- name: orders_freshness
  type: freshness
  column: updated_at
  threshold:
    strategy: static
    max: 60
```

`FreshnessRule.compute()`: read `source.max_value(config.column)` (the contract from 3b guarantees a UTC-aware `datetime` or `None`), compute `(datetime.now(UTC) - latest).total_seconds() / 60`, return it as `freshness_minutes`. No threshold logic in the rule — `StaticThresholdStrategy` already evaluates a float against `max`, unchanged.

Edge cases, resolved without any freshness-specific pass/fail logic:

- **Empty dataset.** `max_value` returns `None` per its existing, already-documented contract. `freshness_minutes` becomes `float("inf")`. No data to be fresh *is* the worst case, not a neutral one (unlike Null Rate's empty-dataset PASS, where "no rows" vacuously means "no rows violate the rule") — `inf` fails any static `max` threshold without `StaticThresholdStrategy` needing to know why.
- **Null timestamps (some rows).** Already handled transparently: `max_value`'s existing contract excludes nulls the same way `distinct_count` does. No change needed.
- **All timestamps null.** Indistinguishable from "empty" at the `max_value` level — `None`, same `inf` handling.
- **Future timestamps.** `max_value` can legitimately be after "now" (clock skew, a batch job that stamped ahead). `freshness_minutes` goes negative, which passes any sane `max` threshold — correctly reads as "very fresh," not flagged as an anomaly. This is a deliberate non-decision: detecting *impossible* freshness as its own anomaly is a Milestone 4/5 concern (statistical/adaptive thresholds), not something a static-threshold Freshness rule should invent.
- **Timezone handling.** Fully owned by the 3b contract at the adapter boundary — the Rule only ever does UTC-aware arithmetic, same convention every existing rule already uses (`datetime.now(UTC)`).

`rule_type = "freshness"`.

---

## Part 5 — Schema Validation Rule

```yaml
- name: orders_schema
  type: schema
  expected_schema:
    order_id: string
    customer_id: string
    amount: decimal
    created_at: timestamp
```

`SchemaValidationRule.compute()`: read `source.columns()`, compare against `config.expected_schema` (3c), classify differences into three buckets — `missing_columns` (in expected, absent from actual), `unexpected_columns` (in actual, absent from expected), `type_mismatches` (present in both, canonical types differ). `value` is the total count across all three buckets; `details` is those three buckets JSON-encoded (3d).

Edge cases:

- **Missing columns.** Counted, named in `details`.
- **Unexpected columns.** Counted, named in `details`. The rule doesn't decide whether an extra column is acceptable — that's exactly what the threshold (`max: 0` vs. a looser bound) is for.
- **Type mismatches.** Comparison is exact canonical-string equality only — no type-compatibility matrix (e.g., treating `integer` and `decimal` as "close enough"). That's a deliberately scoped-out feature, not a missed one: a compatibility matrix is real design surface the milestone's constraints ("no generic abstractions for hypothetical needs") argue against building before a concrete need shows up.
- **Empty dataset.** Handled entirely by `columns()` being structural (Part 3a) — schema comparison runs identically whether the dataset has data rows or not.

`rule_type = "schema"`.

---

## Part 6 — DuckDB vs. PostgreSQL: Backend Comparison

Both adapters must satisfy the same five-method contract identically enough that `FreshnessRule`/`SchemaValidationRule` (and the three existing rules) never branch on which one is running — that's the milestone's actual thesis, not a side effect.

**Aggregates (`row_count`, `null_count`, `distinct_count`).** No meaningful difference — both are standard SQL (`count(*)`, `count(*) WHERE col IS NULL`, `count(DISTINCT col)`), same identifier-quoting convention (double quotes), same NULL semantics.

**`max_value` / timezone.** This is where the backends genuinely diverge. Postgres distinguishes `timestamp without time zone` from `timestamp with time zone` explicitly in `information_schema.columns.data_type`, and a `timestamp with time zone` value comes back from `psycopg` already timezone-aware (normalized to the session timezone, not necessarily UTC). DuckDB's CSV-inferred `TIMESTAMP` type has no timezone concept at all in the common case. Both adapters must converge on the same output per the 3b contract: naive → assume UTC and attach it; aware-but-not-UTC → convert. This logic lives once per adapter, never in the Rule.

**`columns()`.** DuckDB: `DESCRIBE SELECT * FROM read_csv_auto(path)` (or `DESCRIBE read_csv_auto(path)`), mapping DuckDB's returned type strings (`VARCHAR`, `BIGINT`/`INTEGER`, `DOUBLE`, `DECIMAL(p,s)`, `BOOLEAN`, `TIMESTAMP`/`TIMESTAMP WITH TIME ZONE`, `DATE`) to the canonical vocabulary. Postgres: `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = $1` — genuinely parameterized, since here the table name is a *value* bound into a query, not an identifier spliced into SQL text (contrast with the point below).

**Identifiers vs. values.** `DuckDBSource`'s existing docstring already states its trust boundary: file paths and column names come from this process's own local config, never an untrusted caller, so string interpolation for identifiers is acceptable. `PostgresDataSource` inherits the same boundary — the table name comes from `Dataset.config_reference` (local YAML), not network input — so the same reasoning applies; it's restated explicitly in the new adapter's docstring rather than silently assumed. Where Postgres queries a real *value* (a table name string in an `information_schema` `WHERE` clause), real parameter binding is used, since there's no reason not to.

**New dependency.** No Postgres driver exists in `pyproject.toml` today. Proposing `psycopg[binary]>=3.1` (the current, actively maintained driver — not `psycopg2`) as a new `dependencies` entry, same pattern as `duckdb` was added for Milestone 2.

**Verification gap, stated plainly:** I could not run DuckDB in either this cloud session or through the device bridge to this repo — `uv sync` fails from the device bridge with no PyPI egress (same failure the M2 handoff already recorded), and this session's own sandbox also has no route to install `duckdb` from PyPI. So the claim in 3b about DuckDB's current naive/aware behavior on `data/orders.csv`'s `updated_at` column (`2026-08-23T10:00:00Z`) is reasoned from DuckDB's documented CSV-sniffing behavior, not confirmed by running it. Phase B's first task is exactly that confirmation, before `FreshnessRule` is written against an assumption that might be wrong.

---

## Part 7 — `config_reference` Contract for `PostgresDataSource`

`Dataset.config_reference` is one optional string field, and its docstring already treats it as opaque, adapter-specific meaning (`DuckDBSource` reads it as a CSV path). Postgres needs two pieces of information — a connection target and which table to validate — from that same one field. Proposed: a standard connection URL with the table name carried as a query parameter:

```
postgresql://user:password@host:5432/dbname?table=orders
```

`PostgresDataSource.__init__` parses out `table` via `urllib.parse`, uses the remainder as the connection DSN. This keeps `Dataset` and `Policy` completely unchanged — no new field, no schema change — consistent with `config_reference`'s existing design intent ("reserved for exactly this kind of adapter-specific pointer") and with the milestone's own instruction not to modify `DataSource` (or, by the same logic, `Dataset`) without a demonstrated problem. The alternative (a second `Dataset` field for adapter-specific extras) was considered and rejected: it would be a real interface change to solve a problem a URL query parameter already solves for free.

Credentials in a plaintext YAML `config_reference` are a known, named trade-off — acceptable for a local/demo dataset-registration convention (Milestone 2's own filesystem-convention design), explicitly not something to solve with secrets management this milestone (that's platformization-phase work, same phase boundary that keeps a real dataset registry out of scope).

---

## Part 8 — Explicitly Out of Scope (per the brief's own constraints, restated for this design)

No generic SQL builder, no ORM models, no multi-inheritance adapter hierarchy, no plugin framework, no type-compatibility matrix for schema mismatches, no anomaly/statistical handling of future timestamps, no persistence-layer changes (the `details` field is computed but not yet stored), no secrets management for `PostgresDataSource` credentials, no databases beyond DuckDB/Postgres, no adapters built for hypothetical future engines.

---

## Part 9 — Task Breakdown (Phase B Plan, pending approval)

Dependency-ordered; each is independently testable per the brief's instruction.

1. ~~**Verify DuckDB's actual timestamp behavior**~~ — **Not empirically resolved.** No DuckDB was reachable in the environment this milestone was built in. Instead, `_as_utc` (`duckdb_source.py`, `postgres_source.py`) is written to be correct under either naive-or-aware behavior, and `test_max_value_on_a_timestamp_column_is_timezone_aware_utc` deliberately uses timestamps without a `Z` suffix to test the deterministic (naive-input) path only. **Jyoti: confirm locally** by running that test and, if curious, checking what `source.columns()["updated_at"]` reports for `data/orders.csv`.
2. **Done.** `DataSource.columns()` added; `max_value`'s docstring tightened with the UTC contract (3a, 3b). `FakeDataSource.columns()` implemented in `tests/unit/doubles.py`.
3. **Done.** `DuckDBSource.columns()` (DuckDB type → canonical mapping via `_canonical_type`), `max_value` wrapped in `_as_utc`.
4. **Done.** `RuleConfig.expected_schema` (3c), `Metric.details` + `QualityEvent.details` passthrough (3d), with unit tests confirming `details` defaults to `None` for every pre-existing usage.
5. **Done.** `FreshnessRule` (`src/sentinel/rules/freshness.py`) + `tests/unit/rules/test_freshness.py` (fresh, stale, empty, some-null, all-null, future timestamp).
6. **Done.** `SchemaValidationRule` (`src/sentinel/rules/schema_validation.py`) + `tests/unit/rules/test_schema_validation.py` (exact match, missing column, unexpected column, type mismatch, empty-actual-schema).
7. **Done.** Both registered in `registration.py`; `tests/fixtures/policies/orders.yaml`'s freshness threshold fixed (`max_delay_minutes` → `max`, matching `StaticThresholdStrategy`'s actual param name) with `tests/unit/policy_loader/test_loader.py` updated to match; the real `policies/orders.yaml` extended with `orders_freshness` and `orders_schema` rules against `data/orders.csv`'s real columns.
8. **Done.** `PostgresDataSource` (`src/sentinel/datasources/postgres_source.py`): connection/table URL parsing (Part 7), all five `DataSource` methods, `_canonical_type`, `_as_utc`. `psycopg[binary]>=3.1` added to `pyproject.toml`.
9. **Done.** `docker-compose.yml` — a `postgres:16-alpine` service on `localhost:5432`, documented in the root README's new "Local Postgres (Milestone 3)" section.
10. **Done.** `.github/workflows/ci.yml` gained a matching `postgres` service container plus a `SENTINEL_TEST_POSTGRES_DSN` job env var, so cross-adapter tests run in CI, not only locally.
11. **Done.** `tests/integration/test_postgres_duckdb_parity.py`: row count, null rate, uniqueness, and freshness are asserted to produce matching values from `DuckDBSource` and `PostgresDataSource` given the same data; schema validation is asserted against each adapter's own real `columns()` output rather than a predicted cross-backend type match (see that file's module docstring for why — DuckDB's CSV type sniffing and Postgres's declared column types are different type systems, and nothing in this design promises they agree on canonical type for the same logical column). Skips cleanly (not a failure) when Postgres isn't reachable, so `pytest` still passes for a contributor who hasn't run `docker compose up -d`.
12. **Not run.** `uv sync`, `ruff check`, `mypy --strict`, and `pytest` have not been executed against this milestone's code by anyone yet — see the Status line above. Static checks that don't require installed dependencies (`py_compile` across every `.py` file under `src/` and `tests/`, a 100-character line-length sweep, a grep for stray `max_delay_minutes` references) all pass.

---

## Open Questions

1. ~~**`columns()` naming**~~ — **Resolved 2026-08-26: `columns()`**, to avoid overloading "schema" (Postgres has actual SQL schemas/namespaces as a distinct concept).
2. ~~**Canonical type vocabulary**~~ — **Resolved 2026-08-26: use as proposed** — `string | integer | float | decimal | boolean | timestamp | date | unknown`.
3. ~~**`psycopg[binary]` vs. `psycopg2`**~~ — **Resolved 2026-08-26: `psycopg[binary]` v3.**
4. ~~**Local Postgres for dev**~~ — **Resolved by default: docker-compose.** No response changed the default, so `docker-compose.yml` (a single `postgres:16-alpine` service) is what got built; a testcontainers-only approach remains a possible future change if preferred.
5. ~~**`Metric.details` staying unpersisted this milestone**~~ — **Resolved 2026-08-26: yes, defer it.** `sentinel history` won't show schema diffs until a later milestone adds the column; not blocking for M3.

---

## Decisions Log (naming/vocabulary/driver/persistence choices confirmed 2026-08-26; interface changes and the Phase B plan as a whole approved and implemented the same day)

- **One new `DataSource` method** (`columns()` — confirmed), not a generic query escape hatch — preserves the "Rules never see SQL" boundary the Protocol was built to hold.
- **`max_value`'s timezone contract is tightened, not its signature changed** — a documentation/behavior fix, discovered as necessary rather than assumed upfront.
- **`RuleConfig.expected_schema`** as a second dedicated optional field, not a generalized `params` bag — mirrors `column`'s existing precedent instead of introducing a new config shape.
- **`Metric.details: str | None`**, JSON-encoded — the smallest change that lets Schema Validation report structured differences without weakening `Metric`/`ThresholdResult`/`QualityEvent`'s separation of concerns, and without solving frozen-dataclass mutable-field problems the codebase already flagged as unsolved.
- **`config_reference` for Postgres is a connection URL with `table` as a query parameter** — no `Dataset` field added, consistent with `config_reference`'s existing "opaque, adapter-owned" design.
- **`psycopg[binary]`** proposed as the new Postgres driver dependency.
- **Persistence is not extended this milestone** — `details` is computed and displayable, not yet stored; a named, deliberate deferral.
- **CI gains a Postgres service container** — needed for the brief's own "run the same rule tests against DuckDB and PostgreSQL" requirement to be real, not just local-only.
