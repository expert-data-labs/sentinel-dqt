# Sentinel — Milestone 1 Architecture

**Status:** Approved 2026-08-26 — see Part 5 for the task list this now unblocks
**Scope:** Milestone 1 (Functional Core) — three concrete Rules, the Static Threshold Strategy, and the registration wiring that connects them to the registries Milestone 0 already built.

---

## Part 1 — What's Actually New Here

Two of the five deliverables the milestone lists are already satisfied by Milestone 0's work and need no new code:

- **Policy Loader.** `policy_loader/loader.py` already loads YAML, validates it via pydantic, and wraps both parse and schema failures into one `PolicyLoadError` with a useful message. Nothing about Milestone 1 changes what a policy file needs to look like.
- **Structured Validation Results.** `QualityEvent` and `ValidationRun` (`domain/events.py`) already hold everything a quality event needs to be reproducible — the `Metric`, the `ThresholdResult` (verdict + human-readable expectation + which strategy produced it), severity, and `blocking`. This was true the moment Task 2/7 of Milestone 0 landed.

So Milestone 1's real surface area is narrower than the deliverable list suggests: three concrete `Rule` implementations, one concrete `ThresholdStrategy`, and the plumbing that makes the orchestrator able to find them by the string keys a policy YAML names. The `Rule`/`ThresholdStrategy` Protocols and their registries don't change at all.

---

## Part 2 — Rule Engine: Three Concrete Rules

**Metric naming.** Every rule names its `Metric` after the rule's own declared instance name in the policy — `metric_name = config.name` — not after `rule_type`. This isn't a new convention; Milestone 0's `DummyRule` test double already does this. It's what lets two `null_rate` rules on different columns in the same policy produce two distinguishable `QualityEvent`s without `Metric` needing a `dimensions` field.

**`RowCountRule`** (`rules/row_count.py`, `rule_type = "row_count"`):

```python
class RowCountRule:
    rule_type: ClassVar[str] = "row_count"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric:
        return Metric(config.name, source.row_count(), now())
```

No config beyond `name` is required — row count doesn't need a column.

**`NullRateRule`** (`rules/null_rate.py`, `rule_type = "null_rate"`):

Requires `config.column`; raises a clear error if it's absent, per the `Rule` Protocol's documented expectation. Value is `null_count(column) / row_count()`. On an empty dataset (`row_count() == 0`) this divides by zero — I'm treating that as `0.0` rather than raising: `DataSource`'s own contract already treats an empty dataset as a normal state, not an exceptional one, and "no rows to violate the rule" is a defensible reading of a vacuous null rate.

**`UniquenessRule`** (`rules/uniqueness.py`, `rule_type = "uniqueness"`):

Also requires `column`. The metric it reports is a **duplicate count**, not a rate: `(row_count() - null_count(column)) - distinct_count(column)`. Nulls are deliberately excluded from the duplicate arithmetic — `distinct_count` already excludes them per its documented contract, and "are two nulls duplicates of each other" is a null-rate question, not a uniqueness one. Folding it in here would make one rule quietly do two jobs.

`rule_type = "uniqueness"` was chosen over the more mechanical `duplicate_count` because it matches both the milestone's own vocabulary ("Row Count, Null Rate, Uniqueness") and the already-committed `orders.yaml` fixture — no reason to rename a working, PRD-sourced fixture to match an internal metric's shape.

---

## Part 3 — Static Threshold Engine

**`StaticThresholdStrategy`** (`thresholds/static.py`, `strategy_type = "static"`):

```python
class StaticThresholdStrategy:
    strategy_type: ClassVar[str] = "static"

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        ...
```

Reads exactly two keys from `config.params`: `min` and `max`. Either alone is a bound; both together is an inclusive range. Neither present is a configuration error — a new `ThresholdConfigError` (mirroring `PolicyLoadError`, `RuleNotRegisteredError`: one exception type a caller can catch and show a person, rather than a bare lookup failure).

This strategy stays **strictly generic** — no rule-specific param names. The existing `orders.yaml` fixture declares the uniqueness rule's threshold as `{strategy: static, max_duplicates: 0}`; that becomes `{strategy: static, max: 0}` as part of this milestone (Part 5). The alternative — teaching `StaticThresholdStrategy` to recognize `max_duplicates` as an alias for `max` — would be the first crack in an abstraction whose entire value is staying generic across every rule type that uses it.

`ThresholdResult.status` from this strategy is **only ever `PASS` or `FAIL`** — never `WARN`. A plain min/max/range check has no soft band to hang a warning on; `Status.WARN` stays a valid value, reserved for an adaptive strategy (Milestone 4) that actually has two-tier bounds to distinguish.

---

## Part 4 — Registration: Explicit Bootstrap

Nothing currently imports the concrete rule/strategy modules anywhere, so without something to trigger it, none of Milestone 1's `@register_rule`/`@register_threshold_strategy` decorators would ever run.

The chosen mechanism is a new `src/sentinel/registration.py` with one function:

```python
def register_all() -> None:
    """Import every concrete Rule and ThresholdStrategy implementation,
    triggering their registration decorators. Safe to call more than
    once — see note below."""
    from sentinel.rules import row_count, null_rate, uniqueness  # noqa: F401
    from sentinel.thresholds import static  # noqa: F401
```

This was chosen over having `rules/__init__.py`/`thresholds/__init__.py` import their own concrete submodules as a side effect of package import. The explicit form makes "when does registration happen" a visible, callable fact rather than something baked into module-load order — worth the one extra line at each entry point (Milestone 1's tests; Milestone 2's CLI startup, eventually) in exchange for that visibility.

One useful property falls out of using imports as the registration mechanism: Python caches modules in `sys.modules`, so calling `register_all()` more than once (from multiple test files, say) is safe — the second call is a no-op re-import, not a second decorator execution, so it never trips the registry's "already registered" guard.

---

## Part 5 — Fixture Changes and Task Breakdown

**`tests/fixtures/policies/orders.yaml`** needs two edits to match the decisions above:

- `type: volume` → `type: row_count` (the row-count rule)
- `threshold: {strategy: static, max_duplicates: 0}` → `threshold: {strategy: static, max: 0}` (the uniqueness rule)

**New test location:** `tests/integration/`. Everything in Milestone 0 lives under `tests/unit/`, exercising one component against dummies. Milestone 1's defining test is different in kind — a real policy, loaded through the real `load_policy()`, run through the real `ValidationOrchestrator` with all three real Rules and the real `StaticThresholdStrategy` (via `register_all()`), against a `FakeDataSource` seeded from the existing `orders.csv` fixture. No dummies anywhere. That's worth its own directory rather than living alongside orchestrator unit tests that use `DummyRule`.

**Discovered during implementation:** `orders.yaml` also declares a fourth rule, `freshness`, which has no Rule implementation until Milestone 3. Running `orders.yaml` itself through a real (non-dummy) orchestrator today raises `RuleNotRegisteredError` on that rule before it ever reaches the three Milestone 1 rules. Rather than stripping `freshness` out of `orders.yaml` — which would also break the policy loader's own test asserting on all four rules — a new `tests/fixtures/policies/orders_m1.yaml` was added: the same dataset and the same three rule types Milestone 1 implements, nothing else. `orders.yaml` stays the PRD's complete four-rule example for the loader's tests; `orders_m1.yaml` is what the integration test actually runs. Against the PRD's own thresholds (`min: 1000` rows, `max: 0.01` null rate, `max: 0` duplicates), the 12-row `orders.csv` sample fails all three rules — a deliberate, asserted outcome, not a bug: the sample was built to exercise edge cases (one null, one duplicate), not to clear a production-sized row-count bound, and a run that computes and correctly judges real measurements is a stronger proof than one that only happens to pass.

**Task breakdown**, ordered by dependency:

1. **Fixture edits.** The two `orders.yaml` changes above. *Test:* existing loader tests still pass unchanged.
2. **`RowCountRule`.** *Test:* against `FakeDataSource` with N rows, metric value equals N; empty dataset gives 0.
3. **`NullRateRule`.** *Test:* mixed nulls, all-null column, no-null column, empty dataset (→ `0.0`), missing `column` in config raises.
4. **`UniquenessRule`.** *Test:* no duplicates, some duplicates, all-null column (→ 0 duplicates, not `row_count`), missing `column` raises.
5. **`StaticThresholdStrategy` + `ThresholdConfigError`.** *Test:* min-only, max-only, both (in/out of range at each boundary), neither present raises, `ThresholdResult.expected` is a readable string referencing the metric name.
6. **`registration.py: register_all()`.** *Test:* calling it twice doesn't raise; after calling it, `get_rule("row_count")` / `get_threshold_strategy("static")` resolve to the real classes.
7. **End-to-end integration test.** The full `orders.yaml` → `FakeDataSource(orders.csv)` → `ValidationOrchestrator` path described above, asserting on the shape and statuses of the resulting `ValidationRun`.
8. **Close-out verification.** Full suite green, ruff clean, mypy --strict clean — same bar Milestone 0 held itself to.

Tasks 2-5 have no dependency on each other and can happen in any order; 6 depends on 2-5 existing; 7 depends on 6; 8 closes out the milestone.

---

## Decisions Log

- **Policy Loader and Structured Validation Results carry over from Milestone 0 unchanged** — no new work needed for either.
- **Metric naming:** `metric_name = config.name` (the policy's declared rule instance name), not `rule_type` — already established by Milestone 0's `DummyRule`.
- **`RowCountRule` registers as `"row_count"`**, not `"volume"` — the registry only ever supports one implementation per key, so an umbrella-sounding name buys nothing.
- **`UniquenessRule` registers as `"uniqueness"`**, matching the milestone's own vocabulary and the existing `orders.yaml` fixture.
- **Uniqueness's duplicate-count math excludes nulls**, consistent with `distinct_count`'s documented contract.
- **`NullRateRule` on an empty dataset returns `0.0`**, not a division-by-zero error.
- **`StaticThresholdStrategy` stays strictly generic** — `min`/`max`/range only, no rule-specific param aliases. `orders.yaml`'s `max_duplicates` becomes `max`.
- **`StaticThresholdStrategy` never produces `Status.WARN`** — reserved for an adaptive strategy in Milestone 4.
- **Registration is an explicit `register_all()` in a new `registration.py`**, not a package-`__init__.py` side effect — chosen for visibility over convenience; safe to call repeatedly because Python caches module imports.
- **New `tests/integration/` directory** for the one test that wires everything real together, kept separate from Milestone 0's dummy-based unit tests.
- **New `tests/fixtures/policies/orders_m1.yaml`** — the three Milestone-1-implemented rule types only, discovered necessary because `orders.yaml`'s fourth (`freshness`) rule has no implementation until Milestone 3 and would otherwise raise `RuleNotRegisteredError` in a real (non-dummy) orchestrator run. `orders.yaml` is left untouched as the loader's full PRD-example fixture.
- **Milestone 1 stays adapter-agnostic** — the DuckDB adapter is Milestone 3's deliverable per `Project_Milestones.md`; every Milestone 1 test runs against `FakeDataSource`.

The architecture is approved. Starting on Part 5's task list.
