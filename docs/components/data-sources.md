# Data Source Adapters

**Location:** `src/sentinel/datasources/`
**Depends on:** nothing else in Sentinel (`base.py`); the database driver (`duckdb_source.py`, `postgres_source.py`)
**Used by:** `rules` (the interface), `cli` (construction)

An adapter answers a small set of aggregate questions about one dataset. It hides where the data lives, so a rule written once works against every backend.

---

## Interface

```python
# datasources/base.py
class DataSource(Protocol):
    source_type: ClassVar[str]                 # registry key, e.g. "duckdb"

    def row_count(self) -> int: ...
    def null_count(self, column: str) -> int: ...
    def distinct_count(self, column: str) -> int: ...   # excludes nulls
    def max_value(self, column: str) -> Any: ...        # None if empty or all-null; datetimes are UTC-aware
    def columns(self) -> dict[str, str]: ...            # column name -> canonical type
```

The interface exposes **capabilities**, not `execute(sql)`. A generic query method would let rules write dialect-specific SQL, and a rule could then no longer move between backends unchanged. The cost is that the interface grows by one method when a genuinely new kind of measurement is needed. `columns()` was added this way for schema validation.

## Registry

```python
get_data_source(source_type: str, config_reference: str | None) -> DataSource
```

This works like the rule registry: `@register_data_source`, a duplicate-key guard, and `DataSourceNotRegisteredError` for an unknown type. The CLI constructs the adapter from the dataset file's `source_type` and `config_reference`.

---

## Built-in adapters

### `duckdb`: `DuckDBSource`

- **`config_reference`:** path to a CSV file.
- **How it works:** opens an in-memory DuckDB connection and answers each method with one aggregate query over `read_csv_auto('<path>')`. Column types come from `DESCRIBE`.
- **Connection lifetime:** one per `sentinel validate` invocation. It is unrelated to Sentinel's own history store.

### `postgres`: `PostgresDataSource`

- **`config_reference`:** `postgresql://user:password@host:5432/dbname?table=orders`. The `table` query parameter is removed from the URL, and the remainder is the connection string.
- **How it works:** opens one autocommit psycopg 3 connection and runs standard aggregate SQL against the table. Column types come from `information_schema.columns`.

### Canonical column types

Each adapter maps its native types onto one vocabulary so the schema rule can compare across backends.

| Canonical | DuckDB | Postgres |
|---|---|---|
| `string` | `VARCHAR`, `CHAR`, `TEXT`, `BPCHAR` | `character varying`, `character`, `text`, `citext`, `uuid` |
| `integer` | `TINYINT` … `HUGEINT`, unsigned variants | `smallint`, `integer`, `bigint` |
| `float` | `FLOAT`, `DOUBLE`, `REAL` | `real`, `double precision` |
| `decimal` | `DECIMAL(p,s)` | `numeric` |
| `boolean` | `BOOLEAN` | `boolean` |
| `timestamp` | `TIMESTAMP*` | `timestamp*` |
| `date` | `DATE` | `date` |
| `unknown` | anything else | anything else |

For CSV files, DuckDB infers the types itself. If the schema rule reports a mismatch such as `expected decimal, actual float`, that is DuckDB's real inferred type. Update `expected_schema` to match it.

### Timestamps

Both adapters return UTC-aware datetimes from `max_value`: naive values are assumed to be UTC, and aware values are converted to UTC. Rules therefore never deal with time zones.

---

## Trust boundary

Table names, file paths and column names come from local YAML, not from a network caller, so adapters place them into SQL text as quoted identifiers. Do not expose adapters to untrusted input without parameterizing or validating identifiers first.

Postgres credentials sit in plain text in `config_reference`. This is acceptable for local development. For shared environments, source credentials from a secrets manager or environment variables before they reach the YAML.

## Performance characteristics

Each method is a separate query. `DuckDBSource` re-reads the CSV for every call, and a five-rule policy issues roughly eight scans. This is negligible for small and medium files. For large tables, see [Design Decisions D8](../architecture/design-decisions.md#d8-datasource-exposes-capabilities-not-executesql).

---

## Adding an adapter

1. Create `src/sentinel/datasources/<name>_source.py` with a class that has `source_type`, takes `config_reference` in `__init__`, and implements all five methods.
2. Map native types to the canonical vocabulary, and normalize `max_value` datetimes to UTC.
3. Decorate the class with `@register_data_source` and import the module in `registration.register_all()`.
4. Add unit tests, and extend `tests/integration/test_postgres_duckdb_parity.py` (or an equivalent parity test) so every rule is proven to produce the same Metric on the new backend.

## Tests

- `tests/unit/datasources/`: the registry and each adapter
- `tests/integration/test_postgres_duckdb_parity.py`: runs the same rules against the same data in DuckDB and Postgres. It asserts identical values for row count, null rate, uniqueness and freshness, For schema validation, it builds each adapter's expected schema from that adapter's own `columns()` output, so the test does not have to predict which type each engine infers. It skips when `SENTINEL_TEST_POSTGRES_DSN` is not reachable. CI always provides Postgres.
