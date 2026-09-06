# Sentinel — Milestone 5 Architecture (Phase A — Design Review)

**Status: design review only. Nothing in this document has been implemented.**
Per the milestone's own instructions, this is Step 9 ("STOP and present the design
for review") — implementation begins only after this is approved, same gate M4 went
through before its Phase B tasks started.

## Part 1 — Headline Findings

Two things fell out of re-reading the existing domain model before designing anything:

1. **Dataset criticality already exists.** `sentinel.domain.dataset.Criticality`
   (LOW/MEDIUM/HIGH/CRITICAL) has been a required field on `Dataset` since Milestone 0,
   and its own docstring already says: *"Conflating [Criticality and Severity] would
   make it impossible to say 'a HIGH severity rule on a LOW criticality dataset' —
   exactly the kind of context Milestone 5's incident prioritization is supposed to
   combine."* Milestone 5 needs zero new configuration for dataset criticality — no
   YAML changes, no new pydantic model, nothing. It just needs a consumer.

2. **The real gaps are narrower than the milestone brief implies.** Severity
   (`QualityEvent.severity`) and Criticality (`Dataset.criticality`) are both already
   first-class, already flow through the orchestrator, and are already typed as
   4-value enums with overlapping vocabulary but distinct meaning — the exact pattern
   Milestone 5 needs to repeat for `IncidentPriority` (Part 3). What's actually
   missing is: (a) a uniform way to read "how far off is this" across five threshold
   strategies whose `details` shapes differ, (b) a way to see *historical outcomes*
   (not just historical values — `HistoricalMetricsSource` only returns raw
   `Metric`s, with no pass/fail information), and (c) the scoring/classification
   layer itself. Parts 4, 5, and 8 cover these three gaps; everything else is
   plumbing.

## Part 2 — Where Incident Prioritization Belongs

Three placements were considered:

- **Inside `ValidationOrchestrator.run()` directly** — rejected. `run()` already
  does two jobs (compute Metric, evaluate ThresholdStrategy) plus history-fetching
  wiring for Milestone 4. Inlining severity/deviation/frequency/criticality/
  confidence math into the same loop body would make `run()` the one place that
  knows about every domain concept at once — the opposite of the layering this
  codebase has kept clean since Milestone 0.
- **Inside `QualityEvent`** — rejected, and for a reason the milestone brief states
  directly: *"A rule answers what did we observe. A threshold strategy answers is
  this observation anomalous. Incident prioritization answers how important is this
  anomaly."* `QualityEvent` is the *second* answer, already fully assembled by the
  time prioritization has anything to work with (it needs `Dataset.criticality`,
  which isn't in scope of `Metric`/`ThresholdResult` construction at all, and
  historical failure frequency, which needs its own DB read). Mutating or extending
  `QualityEvent` would blur "what happened" with "how much it matters" — the exact
  conflation Criticality's own docstring warns against for Severity vs. Criticality.
- **A separate domain service, invoked by the orchestrator once each `QualityEvent`
  exists** — recommended. Mirrors the Milestone 4 precedent exactly:
  `ValidationOrchestrator` already injects one collaborator
  (`HistoricalMetricsSource`) to fill a gap in what it alone knows, and calls it
  uniformly for every rule regardless of strategy type. Milestone 5 adds a second,
  analogous collaborator (`FailureHistorySource`, Part 5) and a second post-processing
  step (`IncidentPrioritizer.prioritize(...)`, Part 3), called once per `QualityEvent`
  after it's built — never inside a `Rule` or `ThresholdStrategy`, satisfying the
  milestone's explicit constraint.

`IncidentPrioritizer` is a **plain concrete class, not a `Protocol` with a registry**.
`ValidationOrchestrator` itself made this exact call for the same reason (see its own
docstring): a `Protocol`+registry is justified when multiple implementations are
selected at runtime by a config string (`rule_type`, `strategy_type`, `source_type`).
Nothing about incident prioritization is swappable that way — there's one scoring
algorithm, tuned by config values (Part 9), not one of several interchangeable
algorithms chosen per-dataset. Introducing a registry here would be indirection
without payoff, exactly the trap the orchestrator's docstring already named.

## Part 3 — Domain Model

New module: `sentinel/domain/incident.py`.

```python
class IncidentPriority(StrEnum):
    """The final, computed operational priority of an Incident.

    Deliberately a distinct type from Severity and from Criticality, even
    though all three currently share the same four string values
    (info/warning/high/critical for Priority and Severity; low/medium/high/
    critical for Criticality). This is the same distinction Criticality's own
    docstring draws against Severity, extended one level further: Severity is
    declared once in a policy (config-time, per rule); Criticality is declared
    once at dataset registration (config-time, per dataset); IncidentPriority
    is computed at evaluation time (runtime, per QualityEvent) by combining
    both plus deviation/frequency/confidence. Reusing Severity's enum type for
    Priority would make it impossible to distinguish "the rule was configured
    as HIGH severity" from "Sentinel computed HIGH priority for this specific
    occurrence" — which are routinely different (see Part 8's scenarios).
    """
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class IncidentScoreComponents:
    """The five inputs to the scoring model, already normalized to 0-100,
    kept individually rather than only the final sum — this is what makes
    an Incident explainable rather than a black-box number (FR: Part 11)."""
    severity_score: float
    criticality_score: float
    deviation_score: float
    frequency_score: float
    confidence_score: float


@dataclass(frozen=True)
class Incident:
    """What Sentinel concluded, at validation time, about how urgently one
    QualityEvent needs attention. Immutable, same philosophy as Metric/
    ThresholdResult/QualityEvent (Part 10 of the milestone brief) — a
    later change to incident_prioritization's config must never retroactively
    change what an already-recorded Incident says it concluded back then.

    Holds a reference to the QualityEvent it prioritizes rather than
    duplicating its fields (status, severity, actual/expected) — same
    compositional pattern QualityEvent itself uses for Metric/ThresholdResult
    (see domain/events.py's own module docstring).
    """
    quality_event: QualityEvent
    priority: IncidentPriority
    score: float                                # 0-100, already rounded
    components: IncidentScoreComponents
    reasons: tuple[str, ...]                     # human-readable explanation lines
```

**Open question for review:** should `Incident` be produced for *every*
`QualityEvent` (including `PASS`), or only for `WARN`/`FAIL`? The milestone's own
framing — *"Failure → Severity → ... → Incident Priority"* — starts from a failure,
and an `INFO`-priority incident for a passing check adds no operational value I can
see. My recommendation is: **only non-`PASS` events produce an `Incident`**;
`ValidationRun.incidents` (Part 10) will simply be shorter than `quality_events` when
some rules passed. Flagging this explicitly rather than assuming it, since it changes
what "first occurrence" and the boundary tests in Part 12/13 of the milestone brief
actually mean.

## Part 4 — Deviation Magnitude

The milestone brief warns against assuming one deviation calculation fits every
metric type, and against forcing rule-specific logic into a shared place. Looking at
what actually exists:

- `PercentageDeviationStrategy` already stores a normalized `deviation` fraction in
  its JSON `details` (`(actual - baseline) / baseline`).
- `StatisticalThresholdStrategy` / `MedianMadStrategy` / `SeasonalBaselineStrategy`
  store `lower`/`upper`/`center`/`spread` — no single normalized number, but enough
  to derive one: *how many bound-widths past the edge is the actual value*.
- `StaticThresholdStrategy` stores **no** `details` at all today — it only produces
  a human-readable `expected` string (`"row_count >= 1000"`), which isn't safely
  machine-parseable.

Two designs were considered:

- **Push a uniform `deviation_ratio` field onto `ThresholdResult` itself, computed by
  each of the five strategies at `evaluate()` time.** Cleaner long-term (one
  contract, no strategy-type-keyed parsing anywhere else) — but it means touching
  five already-implemented, already-tested Milestone 4 files with prioritization-
  aware logic. That's a direct violation of the milestone's own constraint ("do not
  put strategy-specific prioritization logic into individual ThresholdStrategies")
  and risks regressing code that's already presented and pending your local test run.
- **Recommended: a single, isolated translator inside the new prioritization
  package** (`prioritization/deviation.py`) that reads `ThresholdResult.strategy_type`
  and `.details`, and returns one normalized `deviation_ratio: float | None` (`0.0` =
  exactly at baseline/center, `1.0` = exactly at the configured/computed tolerance
  edge, `>1.0` = beyond it):
  - `percentage_deviation` → `|details.deviation| / details.max_deviation` (both
    already present).
  - `statistical` / `median_mad` / `seasonal` → `|actual - center| / (n_sigma_or_n_mad
    * spread)`, i.e. distance from center measured in the same units the strategy
    already used to define its own bound — equivalent to reusing its own `lower`/
    `upper` as the 1.0 mark.
  - `static` → needs a comparable ratio, but `StaticThresholdStrategy` has no
    `details` to read yet. The one non-strategy-file change I'd propose: give it a
    `details` JSON (`{"actual", "min", "max"}`) — the same additive, backward-
    compatible pattern `Metric.details` and every M4 strategy's `details` already
    established (optional, defaults to `None`, existing tests unaffected). With that,
    ratio = relative distance from whichever bound was breached
    (`|actual - bound| / |bound|`), a documented compromise since a fixed bound has
    no intrinsic "tolerance width" the way an adaptive strategy's spread does.
  - Anything unrecognized (a future strategy_type, or `details=None` with no
    fallback) → `deviation_ratio = None`, and the scoring layer (Part 8) documents
    an explicit default rather than silently guessing (per the brief's edge-case
    requirements).

This keeps every existing threshold strategy file untouched except the one small,
independently-justifiable addition to `static.py` (which arguably should have had
`details` since Milestone 3/4 for consistency's own sake, prioritization aside).

## Part 5 — Historical Frequency

`HistoricalMetricsSource` (Milestone 4) can't answer "how often has this rule
failed" — it returns raw `Metric` values with no pass/fail outcome attached. A
genuinely new abstraction is needed, but the brief is explicit not to over-build it.

New Protocol, `sentinel/prioritization/history.py` (no `duckdb` import, mirroring
`thresholds/history.py`'s own reason for existing):

```python
class FailureHistorySource(Protocol):
    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        """Prior QualityEvent statuses for this (dataset, rule), most recent
        first, capped the same way HistoricalMetricsSource caps its own
        results (a row-count limit, not a wall-clock window — see the
        trade-off note below)."""
        ...

class NullFailureHistorySource:
    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        return ()
```

It returns raw `Status` values (most-recent-first), not a pre-aggregated summary —
same division of labor as `HistoricalMetricsSource` returning raw `Metric`s rather
than a pre-computed baseline: the *source* fetches facts, a *pure function*
interprets them. That pure function lives in `prioritization/frequency.py`:

```python
@dataclass(frozen=True)
class FailureHistory:
    occurrences: int              # count of WARN/FAIL in the observed window
    total_observations: int       # total prior outcomes observed (window size)
    consecutive_failures: int     # trailing streak of WARN/FAIL immediately
                                   # preceding the current evaluation
    is_first_occurrence: bool     # True iff occurrences == 0

def summarize(outcomes: Sequence[Status]) -> FailureHistory: ...
```

`frequency_rate` (mentioned in the brief) is deliberately *not* a stored field —
it's `occurrences / total_observations`, computed on demand where needed, so the
value object stores only facts, not a derived ratio that could drift out of sync
with them.

Concrete implementation: `persistence/failure_history.py` (mirrors
`persistence/history.py`), querying the **existing** `quality_events` joined to
`metrics` and `validation_runs` tables — no schema migration needed, since every
column this needs (`status`, `metric_name`, `dataset_id`, ordering by
`computed_at`) is already persisted by Milestone 2's writer.

**Trade-off flagged for review:** the window is row-count-based (same `limit`
convention as `HistoricalMetricsSource`, e.g. last 90 outcomes), not wall-clock-based
(e.g. "last 30 days"). This is simpler and deterministic (no dependency on "now" at
evaluation time, which also makes it trivially testable), but it means a dataset
validated hourly will accumulate "frequent failure" status faster than one validated
daily for the same underlying failure rate — frequency here really means "how often
relative to how often we checked," not "how often per calendar day." I'd rather ship
this documented limitation than add real-time-window logic the brief explicitly
warns against over-engineering.

## Part 6 — Dataset Criticality

Already fully modeled (Part 1). The only new work is a lookup table mapping
`Criticality` → a numeric score for the scoring model (Part 8) — the same shape of
mapping `Severity` already needs. No YAML, no pydantic changes, no new field
anywhere.

## Part 7 — Anomaly Confidence

Deterministic, explicitly *not* attempting anything ML-like. Available signals,
reusing exactly what Milestone 4 already computes:

- **Strategy family.** `static` has no statistical basis at all (a human-declared
  fixed bound) — it gets a fixed, strategy-level confidence rather than a
  sample-size-derived one. Adaptive strategies (`percentage_deviation`,
  `statistical`, `median_mad`, `seasonal`) derive confidence from history.
- **Sample size (`n_history` / `n_history_in_bucket`).** Already present in every
  adaptive strategy's `details`. A baseline built from 2 points deserves much less
  trust than one built from 90 — confidence scales up with sample size, saturating
  at some point (no meaningful gain in confidence between "90 points" and "900").
- **Strategy robustness.** Milestone 4's own experiment results
  (`docs/experiments/milestone-4-results.md`) are direct, already-measured evidence
  that `median_mad`/`seasonal` are more outlier-resistant than `statistical` on real
  scenarios in this codebase — a small, documented per-strategy multiplier (not
  invented from nothing; it cites the M4 confusion-matrix numbers as its
  justification) nudges `median_mad`/`seasonal` confidence slightly above
  `statistical`/`percentage_deviation` for equivalent sample sizes.
- **Consistency.** If `consecutive_failures > 1` (Part 5), the current failure isn't
  a one-off — it corroborates itself. A small bonus, capped, avoids the formula
  double-counting frequency and confidence into the same signal.

Formula (all constants tunable via config, Part 9):

```
confidence = base(strategy_type)
           * sample_size_factor(n_history)       # adaptive strategies only, else 1.0
           * consistency_factor(consecutive_failures)
```
capped to `[0, 1]`, multiplicative *only within this one component* (not across the
whole scoring model — see Part 8 for why the top-level model stays additive).

**Documented limitation** (per the brief's explicit request to document
insufficiency rather than hide it): for `static` thresholds, and for any adaptive
strategy evaluated with `InsufficientHistoryError` never raised but `n_history`
right at its `min_history` floor, confidence is a genuinely weak signal — there is
no statistical basis to be confident about. The default `base(static)` is
deliberately set to a mid-range value (not 1.0, not 0.0) to reflect "we trust the
business rule, but there's no corroborating statistical evidence" — flagged here as
a judgment call, not a derived number, since the brief explicitly permits exactly
that when the available information is insufficient for anything more principled.

## Part 8 — Scoring Model

Three shapes were compared, per the brief's own list:

**Multiplicative** (`score = severity × deviation × frequency × criticality ×
confidence`) — rejected. A single low factor (e.g. `confidence = 0.1` on a
first-ever failure) collapses the *entire* score toward zero regardless of how
severe or how critical everything else is — the exact "surprising amplification/
suppression" the brief warns against. It also makes monotonicity fragile: whether
increasing one factor increases the product depends on the sign and magnitude of
every other factor at that moment, which is hard to reason about and easy to break
under rounding (the brief calls this out directly).

**Weighted additive** (`score = Σ weight_i × component_score_i`, weights summing to
1.0, each `component_score_i` already normalized to `0-100`) — **recommended**.
- Bounded automatically: with weights summing to 1 and each component in `[0,100]`,
  the sum is always in `[0,100]` — no clamping logic needed anywhere.
- Monotonic by construction: the partial contribution of any one component to the
  total is `weight_i × component_score_i`, so increasing one component while holding
  the others fixed can only increase (never decrease) the sum, as long as each
  component-scoring function is itself monotonic in its own input. That's exactly
  the property the brief asks to test for and worries multiplicative models might
  violate under rounding.
- No component can zero out another's contribution — a CRITICAL-criticality,
  CRITICAL-severity failure with weak confidence still scores meaningfully high,
  which matches operational reality: "we're not fully sure yet" shouldn't hide a
  serious failure on an important dataset, only prevent it from maxing out.
- Each component is independently unit-testable (exactly as the brief's Part 14
  wants) with no interaction effects to reason about.

**Hybrid** (base = severity/criticality, modifiers on top) — the brief's own
suggested alternative. Not rejected outright, but I don't see it buying real
expressiveness over weighted-additive for this scoring problem: severity and
criticality can simply be two (larger-weighted) terms in the same weighted sum,
rather than a structurally separate "base," and doing it that way keeps all five
components in one uniform, symmetric, independently-testable shape instead of two
different mechanisms (a base-lookup plus modifier-multipliers) that would need their
own, separate boundary tests.

**Proposed default weights** (all open to tuning against the seven scenarios in
Part 12 of the milestone brief, once test scenarios exist — do not treat these as
final):

| Component | Weight | Rationale |
|---|---|---|
| Severity | 0.30 | Declared operator judgment about this rule |
| Criticality | 0.30 | Declared business importance of the dataset |
| Deviation | 0.20 | How far off, this occurrence |
| Frequency | 0.10 | How often, historically |
| Confidence | 0.10 | How much to trust the anomaly call itself |

Severity + Criticality intentionally dominate (60%) — they're the two
business-declared inputs the brief's own examples (*"Dataset A: Criticality=LOW,
Failure=severe"* vs. *"Dataset B: Criticality=CRITICAL, Failure=moderate"*) center
on; Deviation/Frequency/Confidence refine within that band rather than override it.

**Priority boundaries** — the brief's own example (0-24 INFO / 25-49 WARNING / 50-74
HIGH / 75-100 CRITICAL) is a reasonable starting split (four even bands) and I'd
propose starting there, then adjusting based on where the seven documented scenarios
actually land once component-scoring functions are pinned down — not before, since
picking boundaries before there's anything to check them against would be guessing.

## Part 9 — Configuration

`IncidentPrioritizationConfig` — a frozen dataclass (not a pydantic model, and
deliberately **not** wired into `Policy`'s YAML this milestone):

```python
@dataclass(frozen=True)
class IncidentPrioritizationConfig:
    weights: ScoreWeights                 # the five weights from Part 8
    priority_thresholds: PriorityThresholds  # the four boundaries from Part 8

DEFAULT_INCIDENT_PRIORITIZATION_CONFIG = IncidentPrioritizationConfig(...)
```

**Why not per-Policy YAML**, even though the milestone brief's own example shows
`incident_prioritization:` nested in what looks like a policy file: scoring weights
and priority boundaries are what make "CRITICAL" mean the same thing everywhere in
the system. If each dataset's policy file could redefine what counts as CRITICAL,
two datasets' CRITICAL incidents would stop being comparable — which undermines the
entire point of a shared operational vocabulary (this is the same reasoning, one
level up, as keeping Severity and Criticality themselves un-conflated). A single,
code-level default is also directly consistent with the brief's own instruction to
"avoid configuration explosion" and "first evaluate whether all of these values
actually need to be configurable" — I don't think they've demonstrated a need yet.

This is a smaller footprint than the brief's sketched YAML, on purpose. It's an
ordinary Python object today; if a real cross-dataset tuning need shows up later,
promoting it to a loadable YAML file (via the existing `load_yaml_model` helper,
same as `Dataset`/`Policy`) is a small, additive change — not a rewrite. Consistent
with `ThresholdConfig`'s own stated philosophy of not growing a schema until a
concrete need forces it.

## Part 10 — Integration With the Validation Flow

`ValidationRun` gains one new field:

```python
@dataclass(frozen=True)
class ValidationRun:
    ...
    quality_events: tuple[QualityEvent, ...]
    incidents: tuple[Incident, ...]   # new — one per non-PASS QualityEvent (Part 3)
```

`ValidationOrchestrator.__init__` gains one new optional collaborator, exactly
mirroring the Milestone 4 `history_source` precedent so every pre-Milestone-5 call
site (including every existing test) keeps constructing `ValidationOrchestrator()`
with no arguments and stays byte-for-byte unaffected:

```python
def __init__(
    self,
    history_source: HistoricalMetricsSource | None = None,
    failure_history_source: FailureHistorySource | None = None,
    prioritizer: IncidentPrioritizer | None = None,
) -> None:
```

Inside `run()`, after each `QualityEvent` is built (same loop, not a second pass over
`policy.rules`): if `event.status is not Status.PASS`, fetch that rule's failure
history and call `prioritizer.prioritize(dataset, event, failure_history)` to get an
`Incident`; append it to a new `incidents` list. `cli/main.py`'s `validate` command
builds a real `DuckDBFailureHistorySource` from the same `context.conn` it already
uses for `DuckDBHistoricalMetricsSource`, and the printed summary gains a priority +
one-line reason per non-passing event (the explainability the milestone requires —
Part 11) — no new CLI command, no dashboard, satisfying the brief's explicit
anti-goals.

**Persistence — open question, not proposed for this milestone.** Nothing in the
Definition of Done requires `Incident` to be written to DuckDB, and
`FailureHistorySource`'s DuckDB implementation only *reads* tables that already
exist (Part 5) — no schema migration is required either way. Milestone 6
("Observability") explicitly wants an "Incident History" view later, which *would*
benefit from a persisted `incidents` table now rather than a migration later — but
that's a Milestone 6 concern, and adding a table/writer/reader trio here would be
scope creep against this milestone's own DoD. I'd default to **not** persisting
Incidents this milestone (keep them an in-memory, per-run result, same as
`ValidationRun` itself is today), and revisit at Milestone 6 — but this is genuinely
your call, so flagging it rather than deciding it.

## Part 11 — Explainability

`Incident.reasons` is a `tuple[str, ...]` of short, human-readable lines built
directly from `IncidentScoreComponents` plus the underlying facts — not reverse-
engineered from the score after the fact. Example, matching the brief's own sample
output:

```
Priority: CRITICAL   Score: 87
Reasons:
  - Dataset criticality: CRITICAL
  - Validation severity: HIGH
  - Deviation: 42% beyond threshold
  - Failure frequency: 8 occurrences in the last 90 observations
  - Anomaly confidence: 0.94 (median_mad, n=64)
```

Because `IncidentScoreComponents` retains every component score (Part 3), nothing
about "why" requires inverting the weighted sum — the explanation *is* the
component breakdown, printed in the same units it was computed in.

## Part 12 — Open Questions Needing Your Decision

Summarizing the judgment calls flagged inline above, since the brief asks me to
stop here rather than resolve these unilaterally:

1. Should `Incident` be produced only for non-`PASS` `QualityEvent`s (my
   recommendation, Part 3), or for every event including `PASS`?
2. Are the proposed default weights (severity 0.30 / criticality 0.30 / deviation
   0.20 / frequency 0.10 / confidence 0.10) and the brief's own 0-24/25-49/50-74/
   75-100 boundaries acceptable as a starting point to validate against the seven
   test scenarios, with the understanding they'll likely shift once real numbers are
   in front of us?
3. Row-count-based history windows (matching Milestone 4's own convention) vs.
   wall-clock windows for failure frequency (Part 5) — I'm recommending row-count
   for determinism and testability; flagging the "hourly vs. daily validation
   cadence" limitation this accepts.
4. Should `Incident` be persisted to DuckDB this milestone (setting Milestone 6 up
   more easily) or stay in-memory only, deferred to Milestone 6 (my recommendation,
   Part 10)?
5. The one non-strategy-behavior change to existing Milestone 4 code: adding
   `details` JSON to `StaticThresholdStrategy` (Part 4), so deviation magnitude is
   computable uniformly. Confirming this is acceptable scope for a "no prioritization
   logic in ThresholdStrategies" milestone, since it's additive/backward-compatible
   but does touch a file you've already reviewed and are pending a local test run on.

## Part 13 — Proposed Phase B Task Sequence (not started)

Once the above is approved, matching the milestone's own numbered sequence (steps
10-17): (1) domain model — `Incident`/`IncidentPriority`/`IncidentScoreComponents`;
(2) `FailureHistorySource` Protocol + Null default + DuckDB-backed implementation;
(3) `deviation.py` translator + the one `static.py` `details` addition; (4)
`frequency.py` pure summarizer; (5) `confidence.py`; (6) `IncidentPrioritizationConfig`
+ defaults; (7) `IncidentPrioritizer` wiring the above into a scored, explained
`Incident`; (8) orchestrator/CLI integration; (9) the seven deterministic scenarios
+ edge cases + boundary tests + monotonicity/invariant tests (brief Parts 12-15);
(10) engineering documentation (brief Part 17); (11) full test suite + lint.

---

# Phase B — Implementation, Verification, and Engineering Analysis

Everything below was implemented after Phase A (above) was reviewed; her decision was to proceed
with every Phase A recommendation as written (Part 12's five open questions all resolved in favor
of the recommended option — non-PASS-only incidents, the proposed default weights/boundaries as an
unvalidated starting point, row-count-based history windows, deferring persistence to Milestone 6,
and adding `details` to `StaticThresholdStrategy`).

## Part 14 — What Was Built

New package `sentinel/prioritization/`: `history.py` (`FailureHistorySource` Protocol +
`NullFailureHistorySource`), `frequency.py` (`FailureHistory` + `summarize()`), `deviation.py`
(`compute_deviation_ratio()`), `confidence.py` (`compute_confidence()`), `config.py`
(`ScoreWeights`, `PriorityThresholds`, `IncidentPrioritizationConfig`), `scoring.py` (the five
`*_score()` functions plus `aggregate_score()`), and `prioritizer.py` (`IncidentPrioritizer`, the
one entry point). New domain module `sentinel/domain/incident.py` (`IncidentPriority`,
`IncidentScoreComponents`, `Incident`). New persistence module
`sentinel/persistence/failure_history.py` (`DuckDBFailureHistorySource`, reading the *existing*
`quality_events`/`metrics`/`validation_runs` tables — no schema migration). `ValidationRun` gained
one new field, `incidents: tuple[Incident, ...]`, defaulting to `()`. `ValidationOrchestrator`
gained two new optional constructor arguments (`failure_history_source`, `prioritizer`), both
defaulting to the Milestone 0-4-compatible null/plain behavior. `sentinel validate`'s printed
summary gained one `priority=... score=...` line per non-passing event. `StaticThresholdStrategy`
gained a `details` JSON output (`actual`/`min`/`max`) — the one change to already-shipped
Milestone 4 code, purely additive and covered by its own regression tests (`test_static.py` re-run
clean, see Part 16).

## Part 15 — Engineering Analysis (milestone brief Part 17)

**1. Why "failure" and "incident priority" are different concepts.** A `QualityEvent`'s status
(`PASS`/`WARN`/`FAIL`) is a judgment about one measurement against one threshold, made with no
knowledge of anything outside that single evaluation. "How urgently should someone act" is a
different question that only makes sense with more context: is this dataset one anyone relies on
(`Dataset.criticality`), has this happened before (`FailureHistory`), and how far off was it
really (`deviation_ratio`)? Two `FAIL` events with identical `Severity` can warrant completely
different responses — collapsing them into one concept would either force every failure to be
treated identically (ignoring real context) or force `Rule`/`ThresholdStrategy` to somehow know
about criticality and history they have no business knowing about (violating the layering Part 2
of Phase A already argued for).

**2. Why dataset criticality must stay separate from validation severity.** `Severity` is an
operator's judgment about one rule, declared once in a policy file, and never changes without a
human editing that file. `Criticality` is a judgment about a dataset's business importance,
declared once at dataset registration, independent of any particular rule. The brief's own
worked example — a `LOW`-criticality dataset with a severe failure vs. a `CRITICAL`-criticality
dataset with a moderate one — is only expressible if the two stay distinct inputs to the same
scoring model; conflating them (e.g. letting `Criticality` silently override `Severity`, or vice
versa) would make one of the two inputs unable to independently express its own judgment.
`sentinel.prioritization.scoring` keeps them as two separate, equally-weighted (0.30 each)
components for exactly this reason — see Part 3's worked numbers below.

**3. How deviation magnitude affects priority.** `deviation_score()` maps a normalized
`deviation_ratio` (0.0 at baseline, 1.0 at the strategy's own tolerance edge) onto 0-100, capping
at twice the edge — so a value that's merely at the boundary of "acceptable" contributes half the
maximum deviation score (50), while anything at or beyond double the tolerance saturates at 100.
This is deliberately metric-agnostic: it reuses whatever tolerance each `ThresholdStrategy` already
computed (a percentage band, a sigma/MAD-scaled interval, a fixed min/max), rather than a
per-metric-name lookup table — see Phase A Part 4 for why that's the "metric-aware but generic"
approach the brief asked for.

**4. Why historical frequency matters.** A failure with no precedent (`is_first_occurrence=True`)
gets a low, fixed frequency score (10/100) regardless of anything else — Scenario 7 verifies this
directly (`test_scenario_7_first_occurrence_does_not_inflate_frequency_score`). A failure that
recurs, especially with an active consecutive streak, is evidence the underlying problem is real
and ongoing, not a transient blip — `frequency_score()` scales with both the overall rate and a
capped consecutive-streak bonus. This is what lets Scenario 4 (moderate deviation, but *frequent*)
reach HIGH/CRITICAL even though its deviation alone wouldn't necessarily justify that.

**5. How anomaly confidence is determined.** Deterministically, from three already-available
signals (`sentinel.prioritization.confidence`): which strategy family produced the verdict (with a
base tier informed by Milestone 4's own measured confusion-matrix results — seasonal and
median/MAD scored higher than statistical and percentage_deviation, matching M4's own documented
findings that the latter two had real, measured weaknesses); how much history backed that
strategy's baseline (more samples, more confidence, floored at 0.5x rather than crushed to zero for
a thin-but-valid sample); and whether the current failure is corroborated by an active consecutive
streak. No ML, no fitted model — every factor is a small, explicit, testable function.

**6/7. Why weighted-additive was chosen, and why multiplicative/hybrid were rejected.** See Phase A
Part 8 in full; the short version verified in Phase B: a weighted sum with weights summing to 1.0
is bounded to [0,100] automatically, and `test_aggregate_score_is_monotonic_in_each_component_
independently` confirms raising any one component while holding the rest fixed never lowers the
total. A multiplicative model was rejected specifically because one weak factor (e.g. low
confidence on a first occurrence) would collapse an otherwise-serious score toward zero — the
"surprising suppression" the brief warned against. A hybrid model wasn't rejected as wrong, just as
not buying enough extra expressiveness to justify two different mechanisms (a base lookup plus
modifiers) over one uniform, symmetric, independently-testable shape.

**8. How the model avoids over-escalating weak anomalies.** Scenario 5
(`test_scenario_5_false_positive_prone_anomaly_is_not_over_escalated`) is the direct test: a value
barely off its baseline, on a thin-history adaptive threshold, produces `deviation_score < 20` and
lands at INFO/WARNING even though *something* technically failed. No single component can push the
result to HIGH/CRITICAL on its own under the additive model — severity and criticality alone
(weighted 0.60 combined) cap out at 60 points if deviation/frequency/confidence are all near zero,
which sits at the WARNING/HIGH boundary, not past it.

**9. How the model avoids under-escalating critical failures.** Scenario 6
(`test_scenario_6_extreme_failure_is_critical`) verifies a severe, high-deviation, frequent,
high-confidence failure on a CRITICAL dataset scores 99.2/100 — every component near its own
maximum, and since the weights sum to 1.0, a near-maximum on every component necessarily produces a
near-maximum total. There's no failure mode symmetric to "one weak factor collapses everything"
under an additive model when every factor is instead strong.

**10. Limitations.** Documented inline where they're most concrete, not buried here: the
failure-history window is row-count-based, not wall-clock (Phase A Part 5) — a dataset validated
hourly accumulates "frequent failure" status faster than one validated daily at the same true
failure rate. Confidence's strategy-family base tiers are coarse judgment calls informed by only
four synthetic Milestone 4 scenarios, not a statistically rigorous ranking (Phase A Part 7). The
default weights and priority boundaries are an explicit starting point, validated only against the
seven scenarios this milestone specifies — not tuned against real production incident data, which
doesn't exist for a portfolio project. `StaticThresholdStrategy`'s deviation ratio is a relative-
distance proxy, not a true "tolerance width" the way adaptive strategies have one, since a fixed
bound has no such concept by construction.

## Part 16 — Verification

Real execution, not hand-simulation, the same standard Milestone 4 set: every new module was
imported and exercised end-to-end in an environment with Python 3.11 + pydantic 2.13 (this
session's cloud sandbox), including a full `ValidationOrchestrator.run()` pass through the real
`row_count` rule and real `static`/`statistical` threshold strategies (via the registries, not
mocked) producing real `Incident`s with sensible scores and reasons. All 201 test functions across
the 8 new test modules (`test_incident.py`, `test_deviation.py`, `test_frequency.py`,
`test_confidence.py`, `test_config.py`, `test_scoring.py`, `test_prioritizer.py`, plus the
Milestone-5 additions to `test_orchestrator.py`) plus the full pre-existing `tests/unit/domain/`
and `tests/unit/thresholds/` suites (regression check for the `static.py`/`events.py` changes) were
executed for real, using a from-scratch minimal pytest-compatible shim (fixtures, `parametrize`,
`raises`, `approx`) since neither this sandbox nor the device VM can install real `pytest` (no
PyPI access, same limitation Milestone 4 documented) — **201 passed, 0 failed**, after two real bugs
this process caught and fixed (both in the tests themselves, not the implementation): a wrong
assumption that two different `StrEnum` types never compare equal by value, and an arithmetic
mistake in a hand-picked deviation-ratio test fixture. `ruff check` (the actual `ruff` binary, using
her exact `pyproject.toml` `select = ["E","F","I","UP","B"]` config) ran clean against every new and
changed file after one auto-fixed import-order issue.

**Not verified anywhere in this session** (same honest gap Milestone 4 disclosed): anything
touching DuckDB directly — `persistence/failure_history.py` and its query — since no environment
available here has the `duckdb` package installed. It mirrors `persistence/history.py`'s own
query shape closely (same tables, same join pattern, same `LIMIT`-based cap) and is syntax/
line-length clean, but only your own `uv run pytest` gives real confirmation of the actual SQL.

## Part 17 — Definition of Done

- [x] Incident prioritization has a clearly defined domain model (`Incident`, `IncidentPriority`,
      `IncidentScoreComponents`).
- [x] Dataset criticality is configurable — pre-existing since Milestone 0, now consumed.
- [x] Validation severity is represented independently (`QualityEvent.severity`, untouched).
- [x] Deviation magnitude contributes to prioritization (`deviation.py` + `scoring.deviation_score`).
- [x] Historical failure frequency contributes (`frequency.py` + `scoring.frequency_score`).
- [x] Anomaly confidence contributes where defensible, with documented limitations
      (`confidence.py`).
- [x] Final priority is one of INFO/WARNING/HIGH/CRITICAL (`IncidentPriority`).
- [x] Scoring is deterministic — no randomness, no ML, anywhere in the pipeline.
- [x] Scoring is explainable — `Incident.reasons`, built directly from `IncidentScoreComponents`.
- [x] Runtime incident results are immutable — `Incident` is a frozen dataclass.
- [x] Rules remain responsible only for producing Metrics — untouched.
- [x] Threshold strategies remain responsible for interpreting Metrics — untouched except the
      additive `details` field on `StaticThresholdStrategy`.
- [x] Prioritization is a separate concern — `sentinel.prioritization`, invoked by the
      orchestrator, never inlined into a Rule or ThresholdStrategy.
- [x] Edge cases are tested — zero history, first occurrence, zero/negative bounds, zero
      expected value, missing details, unrecognized strategy_type, multiple QualityEvents per run.
- [x] Boundary conditions are tested — all three INFO/WARNING/HIGH/CRITICAL cut points.
- [x] Monotonicity/invariant tests exist — deviation, frequency, and each score component
      independently.
- [x] Integration tests cover the complete flow — `ValidationOrchestrator` producing `Incident`s
      end to end, including the default-argument backward-compatibility path.
- [x] Documentation explains the model and its limitations (this section).

Milestone 5 is complete per its own stated Definition of Done. Outstanding, same as Milestones
1-4: your own `uv sync --all-groups && uv run pytest && uv run ruff check . && uv run mypy` for the
one fully authoritative pass (particularly `persistence/failure_history.py`'s real DuckDB query,
which nothing in this session could execute); your call on commit cadence.
