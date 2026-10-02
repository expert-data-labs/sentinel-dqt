# Rule Engine

**Location:** `src/sentinel/rules/`
**Depends on:** `domain`, the `DataSource` interface (`datasources/base.py`)
**Used by:** `orchestration`

A rule **measures** one property of a dataset and returns a `Metric`. It never decides whether that value is acceptable; that is the threshold strategy's job. This split means a rule never needs to change when a threshold does, and a new strategy never requires touching a rule.

---

## Interface

```python
# rules/base.py
class Rule(Protocol):
    rule_type: ClassVar[str]          # registry key, e.g. "null_rate"

    def compute(self, source: DataSource, config: RuleConfig) -> Metric: ...
```

- **Input:** a `DataSource` (where the data is) and the rule's `RuleConfig` (which column, which schema).
- **Output:** one `Metric` whose `metric_name` is `config.name` and whose `value` is a float.
- **Contract:** rules call only `DataSource` methods. They never write SQL and never import a database driver, which is what lets the same rule run unchanged against DuckDB and Postgres.

## Registry

```python
# rules/registry.py
@register_rule                       # adds the class under its rule_type
class NullRateRule: ...

get_rule("null_rate")                # returns a new instance
```

- Registering the same `rule_type` twice raises `ValueError`.
- Looking up an unknown type raises `RuleNotRegisteredError`, and the message lists the known types.
- Implementations are registered when `sentinel.registration.register_all()` imports them.

---

## Built-in rules

| `type` | Class | Requires | Metric value | DataSource calls |
|---|---|---|---|---|
| `row_count` | `RowCountRule` | none | Number of rows | `row_count()` |
| `null_rate` | `NullRateRule` | `column` | Nulls ÷ rows (0.0 for an empty dataset) | `row_count()`, `null_count()` |
| `uniqueness` | `UniquenessRule` | `column` | Duplicate count among non-null values: (rows − nulls) − distinct | `row_count()`, `null_count()`, `distinct_count()` |
| `freshness` | `FreshnessRule` | `column` | Minutes since the latest timestamp in the column | `max_value()` |
| `schema` | `SchemaValidationRule` | `expected_schema` | Number of schema differences | `columns()` |

Pair each rule with a threshold that matches its unit. For example, `uniqueness` with `max: 0` means "no duplicates", and `freshness` with `max: 60` means "updated within the last hour".

### Edge cases

| Rule | Situation | Behaviour |
|---|---|---|
| `null_rate` | Empty dataset | `0.0`: no rows violate the rule. |
| `uniqueness` | Nulls in the column | Ignored. Nulls are neither unique nor duplicates. |
| `freshness` | Empty dataset, or every timestamp null | `inf`. No data is the worst case for freshness, so any `max` fails. |
| `freshness` | Latest timestamp is in the future | Negative minutes, which passes any sensible `max`. |
| `freshness` | Time zones | Adapters return UTC-aware datetimes; naive values are treated as UTC. |
| `schema` | Missing, extra or retyped columns | Each counts as one difference. The breakdown is in `Metric.details` as JSON with `missing_columns`, `unexpected_columns` and `type_mismatches`. |
| `schema` | Type compatibility | Exact match on the canonical type name only. `integer` and `decimal` are different types. |

The schema rule compares against the canonical type vocabulary that every adapter maps to: `string`, `integer`, `float`, `decimal`, `boolean`, `timestamp`, `date` and `unknown`. See [Data Sources](data-sources.md#canonical-column-types).

### Errors

A rule that is missing a required field (`column` or `expected_schema`) raises `RuleConfigError` naming the rule. This aborts the run.

---

## Adding a rule

1. Create `src/sentinel/rules/<your_rule>.py`:

   ```python
   @register_rule
   class MaxValueRule:
       rule_type: ClassVar[str] = "max_value"

       def compute(self, source: DataSource, config: RuleConfig) -> Metric:
           if config.column is None:
               raise RuleConfigError(f"max_value rule {config.name!r} requires a 'column' field")
           return Metric(metric_name=config.name,
                         value=float(source.max_value(config.column)),
                         computed_at=datetime.now(UTC))
   ```

2. Import the module in `sentinel/registration.py::register_all()`.
3. Add `tests/unit/rules/test_<your_rule>.py` using `FakeDataSource` from `tests/unit/doubles.py`.
4. If the rule needs a measurement no `DataSource` method provides, add the method to the `DataSource` Protocol **and to every adapter**, and extend `tests/integration/test_postgres_duckdb_parity.py` so both adapters are proven to agree.

Nothing in the orchestrator, persistence or CLI changes.

## Tests

`tests/unit/rules/`: one file per rule, plus `test_registry.py`. Rules are tested against `FakeDataSource`, so no database is involved.
