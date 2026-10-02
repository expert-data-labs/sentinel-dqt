# Incident Prioritization

**Location:** `src/sentinel/prioritization/`, `src/sentinel/domain/incident.py`
**Depends on:** `domain`
**Used by:** `orchestration`

A failing check tells you *what* went wrong. Prioritization tells you *how much it matters*. Every non-passing `QualityEvent` becomes an `Incident` with:

- a priority (INFO, WARNING, HIGH or CRITICAL)
- a 0–100 score
- the five sub-scores behind it
- five human-readable reasons

The model is deterministic and explainable. There is no machine learning.

---

## Interface

```python
class IncidentPrioritizer:
    def __init__(self, config: IncidentPrioritizationConfig | None = None) -> None: ...
    def prioritize(self, dataset: Dataset, event: QualityEvent,
                   failure_outcomes: Sequence[Status] = ()) -> Incident: ...

class FailureHistorySource(Protocol):           # prioritization/history.py
    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]: ...
```

- `prioritize()` raises `ValueError` if given a PASS event.
- `failure_outcomes` holds the rule's previous statuses, newest first. The real implementation (`persistence.failure_history.DuckDBFailureHistorySource`) returns up to 90.

| File | Role |
|---|---|
| `prioritizer.py` | Coordinates the steps and builds the reasons |
| `scoring.py` | Pure scoring tables and formulas |
| `config.py` | Weights and priority cut-offs (validated) |
| `deviation.py` | How far past the threshold the value was, from `ThresholdResult.details` |
| `frequency.py` | Summarizes past outcomes: occurrences, consecutive failures, first occurrence |
| `confidence.py` | How much to trust the anomaly signal |
| `history.py` | `FailureHistorySource` Protocol and its null implementation |

---

## Scoring model

Each component is scored from 0 to 100.

| Component | Weight | How it is scored |
|---|---|---|
| **Severity** (from the rule) | 0.30 | info 10, warning 40, high 70, critical 100 |
| **Criticality** (from the dataset) | 0.30 | low 10, medium 40, high 70, critical 100 |
| **Deviation** | 0.20 | `ratio ÷ 2 × 100`, capped at 100. 50 if the strategy recorded no details. |
| **Frequency** | 0.10 | 10 for a first occurrence; otherwise failure rate × 100 + 5 per consecutive failure (bonus capped at 30), capped at 100 |
| **Confidence** | 0.10 | `confidence × 100` |

**Deviation ratio**, by strategy:

| Strategy | Ratio |
|---|---|
| `static` | Distance past the violated bound ÷ \|bound\| (2.0 if the bound is 0) |
| `percentage_deviation` | \|deviation\| ÷ `max_deviation` (2.0 if the baseline was 0) |
| `statistical`, `median_mad`, `seasonal` | Distance from the band's centre ÷ half-width (1.0 is exactly on the edge; 2.0 if the band has zero width) |

**Confidence** = strategy base × sample-size factor × consistency factor, clamped to [0, 1]:

- **Strategy base:** static 0.60, percentage_deviation 0.60, statistical 0.65, median_mad 0.75, seasonal 0.80.
- **Sample-size factor:** 1.0 for static. For adaptive strategies it rises from 0.5 to 1.0 as history grows to 30 points.
- **Consistency factor:** 1 + 0.03 per consecutive failure, capped at 1.15.

**Score** = Σ component × weight, rounded to one decimal. **Priority:**

| Score | Priority |
|---|---|
| ≥ 75 | CRITICAL |
| ≥ 50 | HIGH |
| ≥ 25 | WARNING |
| < 25 | INFO |

Weights must sum to 1.0, and cut-offs must be strictly increasing. `IncidentPrioritizationConfig` rejects anything else with `IncidentPrioritizationConfigError`.

### Worked example

`customer_id_not_null` on the `orders` dataset (criticality high, severity warning, static `max: 0.01`, actual 0.083, first ever failure):

| Component | Score | × weight |
|---|---|---|
| Severity: warning | 40 | 12.0 |
| Criticality: high | 70 | 21.0 |
| Deviation: (0.083 − 0.01) ÷ 0.01 = 7.3, capped | 100 | 20.0 |
| Frequency: first occurrence | 10 | 1.0 |
| Confidence: static 0.60 | 60 | 6.0 |
| **Score** | | **60.0, HIGH** |

Reasons, in the order the CLI and dashboard show them:

```text
Dataset criticality: HIGH
Validation severity: WARNING
Deviation: 733% of the tolerance edge (strategy: static)
Failure frequency: first-ever recorded evaluation of this rule
Anomaly confidence: 0.60 (static, n=n/a)
```

With severity `warning` (the default) and criticality `high`, the highest possible score is 73. To let a rule reach CRITICAL, raise its `severity` or mark the dataset `critical`.

---

## Extending

- **Tuning.** Construct `IncidentPrioritizer(IncidentPrioritizationConfig(weights=ScoreWeights(...), thresholds=PriorityThresholds(...)))` and pass it to `ValidationOrchestrator(prioritizer=...)`. The CLI currently uses the defaults.
- **A new threshold strategy.** Add its name to `deviation.py` (to `_BOUND_BASED_STRATEGIES` if it records `lower`, `upper` and `actual`, or a dedicated branch otherwise) and give it a base confidence in `confidence.py`. If you skip this, the strategy still works: deviation scores a neutral 50 and confidence uses a 0.5 base.

## Tests

`tests/unit/prioritization/`: each scoring function, the config validation, deviation per strategy, frequency summarizing, confidence, and end-to-end `prioritize()` output including reasons.
