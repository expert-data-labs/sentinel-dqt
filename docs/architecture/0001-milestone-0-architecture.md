# Sentinel — Milestone 0 Architecture

**Status:** Approved 2026-08-23 — see Part 6 for the task list this now unblocks
**Scope:** Milestone 0 (Architecture & Foundation) only, with an eye toward Milestone 1

---

## Part 1 — The Problem, Restated as a Domain

The PRD's core complaint isn't really "we lack data quality checks." Teams already write those, over and over. The actual failure is architectural: validation logic is welded to pipeline code, thresholds are hardcoded, and there's no shared memory of what "normal" looks like for a given dataset. So a check tells you *what* failed but never *whether it matters*.

Sentinel's job is to pull four concerns apart that pipelines usually tangle together:

1. **What to check** — declared once, as data (a Policy), not as code scattered across pipelines.
2. **How to check it** — reusable Rule implementations that know how to compute a measurement, independent of any one pipeline.
3. **What counts as acceptable** — a Threshold Strategy, decoupled from the Rule, so "is this normal" can evolve from a fixed number to a statistical model without touching the Rule.
4. **What happened, historically** — persisted Runs and Events, so today's failure can eventually be judged against yesterday's.

Reading the PRD's six named concepts against that framing, they split cleanly into two categories that are easy to conflate and shouldn't be:

- **Definitions (config-time, static until someone edits a policy):** Policy, Rule, Threshold.
- **Facts (run-time, produced by execution, immutable once written):** Validation Run, Metric, Quality Event.

That distinction is the single most load-bearing modeling decision in this document — it's what lets the Rule Engine stay ignorant of persistence, and it's what makes "adaptive thresholds" in Milestone 4 an additive change instead of a rewrite.

**Threshold specifically is not one thing — it's a definition/evaluation pair, and the two halves land in different categories above.** The *Threshold Definition* (`ThresholdConfig`: `strategy: static`, `max: 0.01`, and so on) is config-time data, sitting inside a Rule's entry in the Policy, exactly like the Rule's own definition. The *Threshold Evaluation* is runtime behavior — a `ThresholdStrategy` reading a Metric (and, for adaptive strategies, history) and producing a verdict at execution time. This mirrors the Rule split exactly (`RuleConfig` is data, `Rule.compute()` is behavior), and it's why Milestone 4 can introduce `PercentageDeviationStrategy` or `SeasonalStrategy` as new behavior implementations against an unchanged `ThresholdConfig` shape (just new fields for that strategy's own params) rather than redesigning the definition side at all.

One nuance worth flagging: the PRD's `quality_events` table description ("run_id, rule, actual, expected, status, severity") actually bundles two different things — the **measurement** (actual value, what a Rule computed) and the **judgment** (status/severity, what a Threshold Strategy decided). Milestone 0 keeps these as two distinct in-memory objects, **Metric** and **Quality Event**, where a Quality Event *wraps* a Metric plus its evaluation outcome. They can still be persisted into one wide table later — that's a storage decision, not a domain one — but keeping them separate in code is what makes each side independently testable (you can unit-test "does this Rule compute the right row count" without ever invoking a Threshold, and vice versa).

---

## Part 2 — The Smallest Viable Architecture

Milestone 0/1 has no persistence (that's Milestone 2), no API (that's later), and exactly one data source adapter is expected (Milestone 3 adds a second — "only add an adapter after confirming the interface supports it cleanly," per your own milestone notes). Given that, the smallest architecture that still satisfies the PRD's own success criterion —

> "adding a new rule or source should require extending a well-defined platform interface rather than modifying every pipeline"

— is a **single Python package (a modular monolith), organized by domain concept, running entirely in-memory.** No services, no database, no async. The only things that need to be "pluggable" from day one are the four seams the roadmap will actually stress: Rule, Threshold Strategy, Data Source, and the Orchestrator that wires them together. Everything else (Policy, Metric, Validation Run, Quality Event) is a plain, storage-agnostic data object with no behavior of its own — deliberately anemic, because their job is to be *facts*, not actors.

This is the same architecture the PRD's own risk section argues for ("prefer a modular monolith and local-first architecture before introducing services"), so Milestone 0 isn't introducing a new opinion — it's making that one concrete enough to build against.

---

## Part 3 — Simple Functional vs. Domain-Oriented Modular

**Simple Functional Architecture.** Rules and thresholds are plain functions; the orchestrator is a script with an `if rule.type == "volume": ... elif ...` dispatch. This is genuinely less code for three rule types, and it's tempting because Milestone 1 only needs Row Count, Null Rate, and Uniqueness. But it fails the PRD's own definition-of-done: the dispatch chain grows with every new rule type, every new threshold strategy, and every new adapter, and "add a rule" stops meaning "add a file" and starts meaning "edit a central branch." It also gives you nothing to mock in a test — you can't substitute a fake Rule for a real one, because there's no Rule *type*, just a function living in a module.

**Domain-Oriented Modular Architecture.** Each of the four seams (Rule, Threshold Strategy, Data Source, Orchestrator) is an explicit interface (a `typing.Protocol`, not necessarily a heavyweight ABC hierarchy), concrete implementations are small classes registered under a string key, and the orchestrator resolves rule/threshold types through a registry instead of a branch. New rule = new class + one registry line, and the orchestrator never changes. This directly satisfies FR-04 ("pluggable threshold strategy interface") and FR-10 ("adapter contract") as written, and it's also just a better fit for what this project is *for* — the PRD is explicit that Sentinel is a platform-engineering portfolio piece, and "define the interface before adding more" is one of its own stated risk mitigations.

**Recommendation:** Domain-Oriented Modular Architecture, but deliberately undersized — no dependency-injection framework, no repository pattern until Milestone 2 actually needs persistence, no abstract base class hierarchy deeper than one level. "Domain-oriented" here means *module boundaries follow domain concepts*, not that we're importing DDD's full vocabulary (aggregates, value objects, bounded contexts). The registry is a dict and a decorator, not a plugin framework. If Milestone 1 later feels like this was too much ceremony for three rules, that's a cheap signal to revisit — but given Milestone 3 through 5 explicitly add rule types, threshold strategies, and adapters as their entire content, paying for the interface now is paying once instead of three times.

---

## Part 4 — Core Interfaces

Four seams, minimally specified. Each does one job; none of them know about persistence.

**`Rule`** — computes a measurement. It does *not* decide pass/fail; that's the Threshold Strategy's job. Keeping this split means a Rule never needs to know what "acceptable" means, and a new threshold strategy never requires touching a single Rule implementation.

```python
class Rule(Protocol):
    rule_type: ClassVar[str]  # e.g. "volume", "null_rate" — the registry key

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        """Compute one measurement for this rule against the given data source."""
```

**`ThresholdStrategy`** — judges a Metric against configured expectations and returns a verdict. The `history` parameter is included now, as `Optional[Sequence[Metric]] = None`, even though Milestone 1's `StaticThreshold` will ignore it — this is the one place I'm asking you to accept a small amount of forward-looking surface area, because without it, Milestone 4's adaptive strategies (percentage deviation, statistical, seasonal — all of which need history) would force a breaking signature change across every existing implementation and call site.

```python
class ThresholdStrategy(Protocol):
    strategy_type: ClassVar[str]  # e.g. "static", "percentage_deviation"

    def evaluate(
        self,
        metric: Metric,
        params: ThresholdConfig,
        history: Sequence[Metric] | None = None,
    ) -> ThresholdResult:
        """Return a status (pass/warn/fail) and the expectation that was checked."""
```

**`DataSource`** — the adapter contract. This is the interface I'd push back on generalizing further right now: it exposes *capabilities* (`row_count`, `null_count`, `distinct_count`, ...) rather than a generic `execute_query`, because a generic query interface would leak SQL dialect into every Rule and defeat the entire point of FR-10 ("quality logic can operate across multiple data sources without changing rule semantics"). The trade-off is that this interface grows by one method every time a genuinely new *kind* of measurement is needed (schema introspection in Milestone 3 will add one). That's an acceptable, visible cost — better than a leaky abstraction that looks source-independent but isn't.

```python
class DataSource(Protocol):
    def row_count(self) -> int: ...
    def null_count(self, column: str) -> int: ...
    def distinct_count(self, column: str) -> int: ...
    def max_value(self, column: str) -> Any: ...
```

**`ValidationOrchestrator`** — the only component that knows about all three of the above at once. It resolves each configured Rule and Threshold Strategy from their registries, runs the Rule to get a Metric, hands the Metric to the Threshold Strategy to get a verdict, and assembles the result. This is intentionally a single method — there is no reason yet for the orchestrator itself to be swappable; only its collaborators are.

```python
class ValidationOrchestrator(Protocol):
    def run(self, dataset: Dataset, policy: Policy, source: DataSource) -> ValidationRun: ...
```

Not promoted to a named interface, but necessary supporting glue: a small **registry** (a dict keyed by `rule_type` / `strategy_type`, populated via a decorator) that maps policy config strings to concrete classes. It's the mechanism that makes "add a rule = add a file" true, but it's a utility, not a seam anyone will implement multiple versions of — so it doesn't earn Protocol status of its own.

---

## Part 5 — Repository Structure

```
sentinel/
├── pyproject.toml
├── README.md
├── docs/
│   └── architecture/
│       └── 0001-milestone-0-architecture.md   # this document
├── src/
│   └── sentinel/
│       ├── domain/                # pure data objects, no I/O, no behavior
│       │   ├── dataset.py         # Dataset
│       │   ├── policy.py          # Policy, RuleConfig, ThresholdConfig
│       │   ├── metric.py          # Metric
│       │   └── events.py          # QualityEvent, ValidationRun, Status, Severity
│       ├── rules/
│       │   ├── base.py            # Rule Protocol
│       │   ├── registry.py        # @register_rule("volume") etc.
│       │   ├── volume.py          # RowCountRule            (Milestone 1)
│       │   ├── null_rate.py       # NullRateRule            (Milestone 1)
│       │   └── uniqueness.py      # UniquenessRule          (Milestone 1)
│       ├── thresholds/
│       │   ├── base.py            # ThresholdStrategy Protocol
│       │   ├── registry.py
│       │   └── static.py          # StaticThreshold         (Milestone 1)
│       ├── datasources/
│       │   ├── base.py            # DataSource Protocol
│       │   └── duckdb_source.py   # single adapter for M0/M1
│       ├── policy_loader/
│       │   └── loader.py          # YAML -> validated Policy (pydantic)
│       ├── orchestration/
│       │   └── orchestrator.py    # ValidationOrchestrator
│       └── cli/                   # stub package only; filled in Milestone 2
├── tests/
│   ├── unit/
│   │   ├── domain/
│   │   ├── rules/
│   │   ├── thresholds/
│   │   └── orchestration/
│   └── fixtures/
│       ├── policies/orders.yaml   # the PRD's example policy
│       └── data/orders_sample.csv
└── .github/workflows/ci.yml
```

Two things this layout deliberately does *not* have yet, because adding them now would be solving a problem Milestone 0 doesn't have: a `persistence/` package (Milestone 2 introduces it once there's an actual Postgres schema to target — domain objects are already storage-agnostic dataclasses/pydantic models, so nothing here needs to move when that lands), and a `schema.py` / `freshness.py` rule module (Milestone 1's own scope is explicitly Row Count, Null Rate, Uniqueness only — the other two arrive in Milestone 3 alongside the second adapter).

For Milestone 1, the only structural change is filling in the three rule modules and `static.py` above, plus a `StructuredValidationResult`-shaped return type on the orchestrator (already implied by `ValidationRun` + its `QualityEvent` list — Milestone 1 doesn't need a new type, just the real Rule/Threshold logic behind the interfaces Milestone 0 built).

---

## Part 6 — Milestone 0 Task Breakdown

Ordered by dependency; each task should be completable and testable on its own, and each maps to one focused commit/PR.

1. **Repo scaffolding.** `pyproject.toml`, package layout above, linting/formatting/type-checking config (ruff, mypy), `.github/workflows/ci.yml` running lint + `pytest` on push. *Test:* CI goes green on an empty test suite.
2. **Domain objects.** `Dataset` as a pydantic model (it's an external-input boundary — FR-01 fields are human-entered at registration time); `Metric`, `ValidationRun`, `QualityEvent`, `ThresholdResult`, and the `Status`/`Severity` enums as frozen `@dataclass`es — immutable facts, no external input to validate. *Test:* valid construction succeeds; invalid enum values / missing required fields are rejected; a fact object raises on mutation attempts (`frozen=True`).
3. **Policy schema + loader.** Pydantic models for `Policy`, `RuleConfig`, `ThresholdConfig` (the Threshold *Definition* half — see Part 1) matching the PRD's example YAML; a loader function that reads a policy file and returns a validated `Policy`. *Test:* the committed `orders.yaml` fixture loads successfully; a deliberately malformed fixture raises a clear validation error.
4. **Rule interface + registry.** The `Rule` Protocol and the `@register_rule` mechanism — no real rule logic yet, just the contract and a working registration/lookup path. *Test:* register a trivial dummy rule, resolve it by `rule_type` string.
5. **Threshold interface + registry.** Same shape as (4), for `ThresholdStrategy`. *Test:* mirrors (4).
6. **DataSource interface.** The `Protocol` only, with docstring contracts for each method (what exactly does `null_count` mean for an all-null column vs. an empty dataset — these edge cases should be decided in the docstring now, not discovered mid-implementation later). *Test:* a minimal in-memory fake satisfying the Protocol type-checks and can be used as a stand-in.
7. **Orchestrator skeleton.** Implements `run()` against the four interfaces using deliberately fake/stub Rule and ThresholdStrategy implementations, to prove the control flow end-to-end before any real rule logic exists. *Test:* running the orchestrator with a fake rule + fake threshold produces a `ValidationRun` with the expected shape and one `QualityEvent`.
8. **Example policy + fixtures committed.** The PRD's `orders.yaml`, a small sample dataset, wired into the test fixtures directory used by (3) and (7).
9. **Dev environment.** Dependency management (uv vs. Poetry — flagged for your call below), a `Dockerfile` for reproducibility, README with local setup steps. *Verification:* a clean checkout can install deps and run the test suite from the documented steps alone.
10. **Close-out verification.** Full test suite green, CI green on a real PR, and a short pass confirming the four Protocols have no accidental dependency on concrete implementations (i.e., `domain/`, `rules/base.py`, `thresholds/base.py`, `datasources/base.py` import nothing from `orchestration/` or from any concrete rule/adapter module).

Tasks 4–6 have no dependency on each other and can happen in any order once (2) exists; 7 depends on all three; 8 can happen alongside 3; 9–10 close out the milestone.

---

## Decisions Log

- **Threshold = Definition + Evaluation.** `ThresholdConfig` (data, lives in the Policy) is distinct from `ThresholdStrategy` (runtime behavior) — see Part 1.
- **Metric and Quality Event stay separate objects** — a measurement vs. a judgment of that measurement — to keep static and adaptive threshold strategies swappable without touching Rule or Metric code.
- **Architecture style:** Domain-Oriented Modular Architecture, undersized as described in Part 3.
- **Registries:** plain dict + decorator, as described in Part 4.
- **Data modeling boundary:** `@dataclass` (frozen) for immutable runtime facts (`Metric`, `ValidationRun`, `QualityEvent`, `ThresholdResult`) — no external input to validate, only internal invariants to hold. Pydantic stays at the *external configuration boundary* — `Policy`, `RuleConfig`, `ThresholdConfig`, and `Dataset` (registration is itself human-entered input, per FR-01).
- **Milestone 1 adapter: DuckDB** — `datasources/duckdb_source.py`, reflected in the repo layout above.

- **Dependency management: uv.** Single lockfile (`uv.lock`), no separate venv activation step, fast — used from Task 1 onward.

The architecture is approved. Starting on Part 6's task list.
