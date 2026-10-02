# Observability and Dashboard

**Location:** `src/sentinel/observability/`, `dashboard/app.py`
**Depends on:** `domain`, `persistence.engine` (`queries.py` only), `streamlit` (dashboard only)
**Used by:** the dashboard

The observability layer answers "how healthy is our data, and what keeps breaking?" from the facts that validation runs have already persisted. It is **read-only** and never re-implements validation, threshold or prioritization logic.

| File | Role |
|---|---|
| `observability/views.py` | Frozen read models returned to callers |
| `observability/health.py` | Pure derivation rules: dataset health, recurrence classification. No database access. |
| `observability/queries.py` | `ObservabilityQueryService(conn)`: one method per view, each a single aggregating query |
| `dashboard/app.py` | Streamlit app. Reads only through `ObservabilityQueryService`. |

---

## Query service

```python
service = ObservabilityQueryService(conn)
```

| Method | Returns | Window |
|---|---|---|
| `dataset_health(dataset_id)` | `DatasetHealthView` | Latest run only |
| `all_datasets_health()` | `list[DatasetHealthView]` | Latest run per dataset |
| `quality_history(dataset_id, window, as_of)` | `list[QualityHistoryEntry]`: per run, rules evaluated/failed, overall status, highest priority | Calendar |
| `metric_trend(dataset_id, metric_name, window, as_of)` | `list[MetricTrendPoint]`: value, timestamp, threshold details | Calendar |
| `rule_names_for_dataset(dataset_id)` | `list[str]` | All time |
| `failed_rules(window, as_of, dataset_id=None)` | `list[FailedRuleView]`: failure count, latest failure, current priority | Calendar |
| `incident_history(window, as_of, dataset_id=None, priority=None, rule_name=None)` | `list[IncidentHistoryEntry]` | Calendar |
| `recurring_failures(window, as_of, dataset_id=None)` | `list[RecurringFailureView]` | Calendar, plus each pair's latest status |

`window` is a `TimeWindow`: `LAST_24H`, `LAST_7D` or `LAST_30D`. Every windowed method takes an explicit `as_of` instead of calling `now()`, which keeps tests deterministic. "Failure" everywhere means a non-PASS `quality_events` row, the same boundary the orchestrator uses to decide whether to prioritize.

Each view is one aggregating query (`GROUP BY`, window functions), not a query per dataset or per rule.

## Derived states

**Dataset health** (`health.derive_dataset_health`) is computed from the dataset's **latest** run:

| Health | Condition |
|---|---|
| `UNKNOWN` | The dataset has never been validated |
| `HEALTHY` | Latest run produced no incidents |
| `DEGRADED` | Highest incident priority is INFO, WARNING or HIGH |
| `CRITICAL` | Highest incident priority is CRITICAL |

Health uses incident *priority*, not raw status. A low-priority failure should not look as alarming as a critical one.

**Recurrence** (`health.classify_recurrence`) is computed per (dataset, rule) within the selected window:

| Classification | Condition |
|---|---|
| `FIRST_OCCURRENCE` | One failure in the window |
| `RECURRING` | Two or more failures in the window, and the latest evaluation passed |
| `PERSISTENT` | Two or more failures in the window, and the latest evaluation (ever) also failed |

This calendar window is intentionally different from the prioritizer's "last 90 evaluations" window. See [Design Decisions D16](../architecture/design-decisions.md#d16-two-different-windows-for-repeated-failure).

---

## Dashboard

```bash
uv sync --group dashboard
uv run streamlit run dashboard/app.py
```

The dashboard reads `SENTINEL_DATABASE_URL` like the CLI. Run `sentinel validate` a few times first so there is history to show.

| Section | Content |
|---|---|
| Sidebar | Time window (default: last 7 days) and an optional dataset drill-down |
| Dataset Health | Every dataset's current health, latest validation time, highest priority and failed rule count. Not affected by the time window. |
| Recent Incidents | Incidents in the window with priority, score and top reason |
| Failed Rules | Rules with failures in the window, most frequent first, with their current priority |
| Recurring Failures | First occurrence, recurring or persistent, per dataset and rule |
| Metric Trends | Line chart of one rule's metric over the window, plus the latest threshold details. Requires a selected dataset. |
| Quality History | Per-run summary for the selected dataset |

**Notes:**

- Streamlit is an optional dependency group, so CLI-only users never install it.
- The dashboard shares a small connection pool across all viewer sessions and borrows one connection per page render. It can run alongside any number of `sentinel validate` processes.
- The dataset drill-down passes the dataset **name** as the id. Keep `id` and `name` identical in dataset YAML (the bundled examples do).

---

## Adding a view

1. Add a frozen read model to `views.py`.
2. If the view involves a judgement ("what counts as X"), add it as a pure function in `health.py` and unit-test it with plain inputs.
3. Add one method to `ObservabilityQueryService` that fetches rows with a single query and calls the pure function.
4. Render it in `dashboard/app.py`. Keep the dashboard free of logic.
5. Add query tests using the deterministic fixture in `tests/unit/observability/fixtures.py`.

## Tests

- `tests/unit/observability/test_health.py`: health and recurrence rules
- `tests/unit/observability/test_queries.py`: every view against a seeded store with a fixed `as_of`
- `tests/integration/test_observability_end_to_end.py`: real validation runs, then reads back through the service
- The Streamlit app itself has no automated tests. It contains no business logic.
