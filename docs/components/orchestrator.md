# Validation Orchestrator

**Location:** `src/sentinel/orchestration/orchestrator.py`
**Depends on:** `rules`, `thresholds`, `datasources` (interface only), `prioritization`, `domain`
**Used by:** `cli`

`ValidationOrchestrator` runs one Policy against one Dataset and returns one immutable `ValidationRun`. It is the only component that knows about rules, strategies and the prioritizer at once. It does no persistence and opens no connections of its own.

---

## Interface

```python
class ValidationOrchestrator:
    def __init__(self,
                 history_source: HistoricalMetricsSource | None = None,       # default: NullHistorySource
                 failure_history_source: FailureHistorySource | None = None,  # default: NullFailureHistorySource
                 prioritizer: IncidentPrioritizer | None = None) -> None: ...

    def run(self, dataset: Dataset, policy: Policy, source: DataSource) -> ValidationRun: ...
```

Each dependency defaults to a do-nothing version. `ValidationOrchestrator()` with no arguments is fully functional: static thresholds work, and every failure is treated as a first occurrence. Tests rely on this, and the CLI injects the real DuckDB-backed sources.

## Algorithm

```text
started_at = now()
for rule_config in policy.rules:                        # policy order
    metric    = get_rule(rule_config.rule_type).compute(source, rule_config)
    history   = history_source.get_history(dataset.id, rule_config.name)
    result    = get_threshold_strategy(rule_config.threshold.strategy)
                    .evaluate(metric, rule_config.threshold, history)
    event     = QualityEvent(rule_config.severity, rule_config.blocking, metric, result)
    if event.status is not PASS:
        outcomes = failure_history_source.get_outcomes(dataset.id, rule_config.name)
        incident = prioritizer.prioritize(dataset, event, outcomes)
finished_at = now()
return ValidationRun(dataset, policy.version, started_at, finished_at,
                     status=worst(event statuses), quality_events, incidents)
```

- **Status aggregation.** FAIL is worse than WARN, which is worse than PASS. The `blocking` flag is **not** considered here. Blocking affects only the CLI's exit code. See [Design Decisions D4](../architecture/design-decisions.md#d4-run-status-and-pipeline-exit-code-are-different-judgements).
- **History is fetched uniformly.** The orchestrator never checks which strategy it is about to call. Static strategies receive history and ignore it. This keeps the orchestrator free of strategy-specific branches, at the cost of one small query per rule.
- **Prioritization only for non-PASS events.** A passing rule never triggers a failure-history lookup or produces an Incident.
- **No state between runs.** Nothing about a run is stored on `self`, so one instance can run many datasets in sequence.

## Error handling

The orchestrator does not catch exceptions. Each of the following propagates to the caller, and no `ValidationRun` is returned:

| Raised by | Error |
|---|---|
| Registry lookup | `RuleNotRegisteredError`, `ThresholdStrategyNotRegisteredError` |
| Rule | `RuleConfigError`, or any database error from the `DataSource` |
| Strategy | `ThresholdConfigError`, `InsufficientHistoryError` |

This is a deliberate choice: a single failing rule aborts the whole run rather than producing a partial result that looks complete. Wrapping these into a unified error type, or recording per-rule execution errors as events, is a natural next step once a caller needs it.

## Why it is a concrete class

`Rule`, `ThresholdStrategy` and `DataSource` are Protocols because several implementations are selected at runtime by a config string. Nothing selects between orchestrators that way, so a Protocol here would be indirection without payoff. If a second implementation appears (for example one that evaluates rules in parallel), extracting a Protocol is a small, additive change.

## Tests

`tests/unit/orchestration/test_orchestrator.py` uses `FakeDataSource`, `DummyRule` and `DummyThresholdStrategy` from `tests/unit/doubles.py`. It covers:

- event assembly
- status aggregation
- history being passed through
- incidents being produced only for non-PASS events
