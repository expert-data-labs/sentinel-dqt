# Threshold Strategies

**Location:** `src/sentinel/thresholds/`
**Depends on:** `domain`
**Used by:** `orchestration`

A threshold strategy **judges** a Metric. It decides PASS or FAIL against the configured parameters and, for adaptive strategies, against the same metric's past values.

---

## Interface

```python
# thresholds/base.py
class ThresholdStrategy(Protocol):
    strategy_type: ClassVar[str]                     # registry key, e.g. "median_mad"

    def evaluate(self, metric: Metric, config: ThresholdConfig,
                 history: Sequence[Metric] = ()) -> ThresholdResult: ...
```

- **Input:** today's Metric, the rule's `ThresholdConfig` (`config.params` holds the strategy's parameters), and past Metrics for the same dataset and rule, newest first.
- **Output:** a `ThresholdResult` containing:
  - `status`
  - `expected`, a one-line human description such as `row_count within [963, 1052] (median=1005, ±3 scaled MAD, n=5)`
  - `strategy_type`
  - `details`, JSON with the baseline, bounds, deviation and sample size
- **Contract:** strategies are pure functions. They never fetch history themselves, which is why they can be unit-tested with a list of numbers.

## History

```python
# thresholds/history.py
class HistoricalMetricsSource(Protocol):
    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]: ...

class NullHistorySource:              # always returns ()
```

The orchestrator calls `get_history(dataset.id, rule.name)` for every rule and passes the result to `evaluate()`. The real implementation is `persistence.history.DuckDBHistoricalMetricsSource`, which returns up to 90 past values, newest first. `thresholds/` never imports it; the CLI injects it.

History contains **values only**, never past verdicts. Changing a rule's strategy keeps its history intact.

---

## Built-in strategies

| `strategy` | Class | Parameters (defaults) | PASS when |
|---|---|---|---|
| `static` | `StaticThresholdStrategy` | `min`, `max` (at least one required) | `min ≤ value ≤ max`; history is ignored |
| `percentage_deviation` | `PercentageDeviationStrategy` | `max_deviation` (required, e.g. `0.15`), `min_history` (1) | \|value − mean(history)\| ÷ mean ≤ `max_deviation` |
| `statistical` | `StatisticalThresholdStrategy` | `n_sigma` (3.0), `min_history` (2, minimum 2) | value within mean ± `n_sigma` × stdev |
| `median_mad` | `MedianMadStrategy` | `n_mad` (3.0), `min_history` (2) | value within median ± `n_mad` × 1.4826 × MAD |
| `seasonal` | `SeasonalBaselineStrategy` | `dimension` (`day_of_week`, the only option), `n_sigma` (3.0), `min_history` (2 per bucket) | value within mean ± `n_sigma` × stdev of past values **from the same weekday** |

Shared statistics live in `thresholds/_stats.py` (`mean_stddev_bounds`, `median_mad_bounds`). `seasonal` reuses `mean_stddev_bounds` on each weekday bucket.

### Example

```yaml
- name: daily_orders
  type: row_count
  threshold:
    strategy: median_mad
    n_mad: 3
    min_history: 7
```

### Choosing a strategy

These recommendations come from the controlled comparison in [Threshold Strategy Evaluation](../experiments/threshold-strategy-evaluation.md).

| Data shape | Use | Avoid |
|---|---|---|
| A hard business limit (no nulls, no duplicates, at least N rows) | `static` | adaptive strategies, which would learn to accept a bad baseline |
| One stable level, deviations matter in relative terms | `percentage_deviation` | it on multi-modal data (its single mean sits between clusters) |
| Unimodal, roughly normal, clean history | `statistical` | it when history may contain past anomalies |
| Occasional extreme outliers in history | `median_mad` | it on data with a recurring pattern (it rejects the minority cluster) |
| A weekly pattern, such as weekday/weekend volume | `seasonal` | it with little history (each weekday bucket needs its own samples) |

Headline result from the evaluation, on six weeks of weekday ≈ 1000 / weekend ≈ 500 data with one real anomaly:

- `static` raised 12 false alarms (every weekend).
- `seasonal` raised 2 and caught the anomaly.
- `percentage_deviation` raised 26.
- `statistical` raised 0 but **missed the anomaly**, because mixing two populations inflated its bounds.

### Edge cases

| Situation | Behaviour |
|---|---|
| `percentage_deviation` with baseline 0 and value 0 | PASS (0% deviation) |
| `percentage_deviation` with baseline 0 and value ≠ 0 | FAIL, with a note in `details` (relative deviation is undefined) |
| Zero variance in history (stdev or MAD = 0) | Bounds collapse to a single point; any change fails |
| Anomalies already in history | `statistical` widens its bounds and may miss a repeat. `median_mad` is robust to this. |

---

## Errors

| Error | Meaning | Fix |
|---|---|---|
| `ThresholdConfigError` | A required parameter is missing or invalid, for example `static` with neither `min` nor `max` | Edit the policy |
| `InsufficientHistoryError` | Fewer past values than `min_history` (per weekday for `seasonal`) | Accumulate more runs (see below) |
| `ThresholdStrategyNotRegisteredError` | Unknown `strategy` name | Check spelling, or register the strategy |

All three abort the run, so nothing from that run is persisted.

### Cold start

Because `InsufficientHistoryError` aborts the run before persistence, a **new** rule configured directly with an adaptive strategy can never accumulate the history it needs. Until the run path handles this case, bootstrap as follows:

1. Start the rule with `strategy: static` and a generous bound.
2. Run it until it has at least `min_history` runs (for `seasonal`, `min_history` of *each* weekday).
3. Switch the rule to the adaptive strategy, **keeping the same rule `name`**. History is keyed by name, not by strategy, so it carries over.

### Choosing and tuning a strategy

`python -m examples.simulate` replays weeks of daily loads, with anomalies injected on known days, through the real pipeline (following the cold-start steps above), and prints a scorecard of caught, missed and false alarms for every rule in `policies/simulated_orders.yaml`. Edit the policy, rerun, and compare. See the [examples guide](../examples.md#10-testing-adaptive-thresholds-with-the-simulator).

---

## Adding a strategy

1. Create `src/sentinel/thresholds/<name>.py` with a class that has `strategy_type` and `evaluate()`.
2. Read parameters from `config.params`, and raise `ThresholdConfigError` for invalid ones and `InsufficientHistoryError` for too little history.
3. Put the computed baseline, bounds, `actual` and `n_history` into `details`. The prioritizer reads these keys to score deviation and confidence. Then add the strategy to `prioritization/deviation.py` and `prioritization/confidence.py` (see [Incident Prioritization](prioritization.md#extending)).
4. Register the class with `@register_threshold_strategy` and import the module in `registration.register_all()`.
5. Add unit tests, and add the strategy to `experiments/threshold_intelligence/runner.py` to see how it behaves on the four scenarios.

No rule, adapter, orchestrator or persistence change is needed.

## Tests

- `tests/unit/thresholds/`: one file per strategy, plus `test_stats.py`, `test_history.py` and `test_registry.py`
- `tests/unit/experiments/test_runner.py`: pins the evaluation's documented outcomes so they cannot drift silently
