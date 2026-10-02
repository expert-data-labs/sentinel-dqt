# Data Source Adapters

**Location:** `src/sentinel/datasources/`
**Depends on:** nothing else in Sentinel (`base.py`); each adapter's database driver
**Used by:** `rules` (the interface), `cli` and `validation_service` (construction)

An adapter answers a small set of aggregate questions about one dataset. It hides where the data lives, so a rule written once works against every backend.

| `source_type` | Reads | Driver | Install |
|---|---|---|---|
| `duckdb` | CSV, Parquet, JSON files, local or on S3 | `duckdb` | included |
| `postgres` | A Postgres table or view | `psycopg` | included |
| `mysql` | A MySQL / MariaDB table | `pymysql` | `sentinel[mysql]` |
| `snowflake` | A Snowflake table or view | `snowflake-connector-python` | `sentinel[snowflake]` |
| `bigquery` | A BigQuery table or view | `google-cloud-bigquery` | `sentinel[bigquery]` |
| `mongodb` | A MongoDB collection | `pymongo` | `sentinel[mongodb]` |

Optional drivers are only imported when a dataset uses that source. If one is missing, the run fails with a message naming the extra to install (`pip install 'sentinel[snowflake]'` or `uv sync --extra snowflake`). `sentinel[all-sources]` installs every driver.

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

This works like the rule registry: `@register_data_source`, a duplicate-key guard, and `DataSourceNotRegisteredError` for an unknown type. Before constructing the adapter it expands `${ENV_VAR}` references in `config_reference` (see [Credentials](#credentials)).

---

## How the adapters are built

```text
DataSource (Protocol)
├── SqlDataSource (sql_base.py)   row_count / null_count / distinct_count / max_value
│   ├── DuckDBSource               table = read_csv_auto | read_parquet | read_json_auto
│   ├── PostgresDataSource         "schema"."table", information_schema
│   ├── MySQLDataSource            `table`, information_schema
│   ├── SnowflakeDataSource        "DB"."SCHEMA"."TABLE", information_schema
│   └── BigQueryDataSource         `project`.`dataset`.`table`, table schema API
└── MongoDataSource                aggregation pipelines
```

The SQL engines answer every capability with the same aggregate SQL (`COUNT(*)`, `COUNT(*) ... IS NULL`, `COUNT(DISTINCT ...)`, `MAX(...)`), so `SqlDataSource` implements them once. A SQL adapter supplies only:

- `_table()`: how to reference the dataset in `FROM`
- `_scalar(query)`: run a query and return its single value
- `columns()`: schema introspection, which differs per engine
- `_quote_char`: `"` or a backtick

Identifiers are always quoted, with embedded quote characters doubled, so a column name from YAML can't break out of the SQL.

MongoDB has no SQL, so `MongoDataSource` implements the Protocol directly.

---

## Configuration per source

### `duckdb`: files

```yaml
config_reference: data/orders.csv                 # CSV / TSV, optionally .gz
config_reference: data/events/*.parquet           # globs read every matching file
config_reference: s3://lake/orders/2026/*.parquet # S3
config_reference: data/events.jsonl               # JSON or newline-delimited JSON
```

The reader is chosen by extension (`.csv`, `.tsv`, `.parquet`, `.json`, `.jsonl`, `.ndjson`). For S3, credentials come from the standard AWS chain (environment variables, `~/.aws`, instance roles); DuckDB installs its `httpfs` and `aws` extensions on first use. Every query re-reads the files.

### `postgres`

```yaml
config_reference: postgresql://etl:${PG_PASSWORD}@db:5432/shop?table=orders
config_reference: postgresql://etl:${PG_PASSWORD}@db:5432/shop?table=sales.orders&sslmode=require
```

`table` may be `schema.table`. Other parameters go to libpq.

### `mysql`

```yaml
config_reference: mysql://etl:${MYSQL_PASSWORD}@db:3306/shop?table=orders
```

`tinyint(1)` (MySQL's BOOLEAN) maps to `boolean`. `DATETIME` values are assumed to be UTC.

### `snowflake`

```yaml
config_reference: snowflake://etl:${SNOWFLAKE_PASSWORD}@xy12345.eu-west-1/ANALYTICS/SALES?warehouse=COMPUTE_WH&role=QA&table=orders
config_reference: snowflake://etl@myorg-acct/ANALYTICS/SALES?authenticator=externalbrowser&table=orders
```

The host is the account identifier, the path is `database/schema`. Other parameters (`warehouse`, `role`, `authenticator`, `private_key_file`, ...) go to `snowflake.connector.connect`.

Names follow Snowflake's rules: a plain lower-case name such as `orders` or `order_id` refers to the upper-case object (`ORDERS`), as unquoted SQL would. Mixed-case names are used exactly. `columns()` reports upper-case names in lower case, so `expected_schema` can be written in lower case. `NUMBER` with scale 0 is `integer`; with a scale, `decimal`.

### `bigquery`

```yaml
config_reference: bigquery://my-project/sales?table=orders
config_reference: bigquery://my-project/sales?table=orders&location=EU
```

Credentials come from Google Application Default Credentials (`gcloud auth application-default login` locally; a service account or workload identity in production), so none appear in the config. BigQuery bills by bytes scanned: `row_count` reads table metadata only, the other checks scan one column each. `REPEATED` and `RECORD` fields are `unknown`.

### `mongodb`

```yaml
config_reference: mongodb://etl:${MONGO_PASSWORD}@db:27017/shop?collection=orders&authSource=admin
config_reference: mongodb+srv://etl:${MONGO_PASSWORD}@cluster0.example.net/shop?collection=orders
```

| Capability | MongoDB behaviour |
|---|---|
| Column names | Field paths; `customer.id` reaches into sub-documents |
| `null_count` | Counts documents where the field is null **or missing** |
| `distinct_count`, `max_value` | Ignore null and missing values; cross-type comparisons follow MongoDB's BSON ordering |
| `columns()` | Inferred from a random sample (`schema_sample=N`, default 1000) of top-level fields. A field seen with two types is `unknown`; ObjectId is `string`. An empty collection has no columns. |

---

## Canonical column types

Each adapter maps native types onto one vocabulary so the schema rule can compare across backends.

| Canonical | DuckDB | Postgres | MySQL | Snowflake | BigQuery | MongoDB |
|---|---|---|---|---|---|---|
| `string` | `VARCHAR`, `UUID` | `text`, `varchar`, `uuid` | `varchar`, `text`, `enum` | `TEXT` | `STRING` | string, ObjectId |
| `integer` | `INTEGER`, `BIGINT`, ... | `integer`, `bigint` | `int`, `bigint`, ... | `NUMBER(p,0)` | `INT64` | int, long |
| `float` | `DOUBLE`, `FLOAT` | `double precision`, `real` | `double`, `float` | `FLOAT` | `FLOAT64` | double |
| `decimal` | `DECIMAL(p,s)` | `numeric` | `decimal` | `NUMBER(p,s)` | `NUMERIC` | decimal |
| `boolean` | `BOOLEAN` | `boolean` | `tinyint(1)` | `BOOLEAN` | `BOOL` | bool |
| `timestamp` | `TIMESTAMP*` | `timestamp*` | `datetime`, `timestamp` | `TIMESTAMP_*` | `TIMESTAMP`, `DATETIME` | date |
| `date` | `DATE` | `date` | `date` | `DATE` | `DATE` | n/a |
| `unknown` | anything else | | | | | |

For files, DuckDB infers the types itself. If the schema rule reports a mismatch such as `expected decimal, actual float`, that is DuckDB's real inferred type. Update `expected_schema` to match it.

### Timestamps

Every adapter returns UTC-aware datetimes from `max_value`: naive values are assumed to be UTC, and aware values are converted to UTC. Rules therefore never deal with time zones.

---

## Credentials

Never put passwords in dataset YAML. `config_reference` may reference environment variables, which are expanded only when the adapter is created:

```yaml
config_reference: snowflake://etl:${SNOWFLAKE_PASSWORD}@acct/ANALYTICS/SALES?warehouse=WH&table=orders
```

The YAML (and the copy stored in Sentinel's `datasets` table) keeps the `${...}` reference, not the secret. An unset variable fails the run with its name. Supply the variables from your scheduler's or CI's secret store. BigQuery and S3 need no secrets in the config at all; they use their platforms' credential chains.

## Trust boundary

Table, file and column names come from local YAML, not from a network caller. They are quoted and escaped, but adapters should still not be exposed to untrusted input.

## Performance characteristics

Each capability is one query, and a five-rule policy issues roughly eight. That is negligible for files and indexed tables. On warehouses, each query scans the columns it touches; on very large tables, point the dataset at a view or a recent partition. See [Design Decisions D8](../architecture/design-decisions.md#d8-datasource-exposes-capabilities-not-executesql).

---

## Adding an adapter

1. **SQL engine:** subclass `SqlDataSource` in `src/sentinel/datasources/<name>_source.py`; set `source_type` (and `_quote_char` if not `"`), and implement `__init__(config_reference)`, `_table()`, `_scalar()` and `columns()`. **Anything else:** implement the five Protocol methods directly, as `MongoDataSource` does.
2. Map native types to the canonical vocabulary. Return UTC-aware datetimes from `max_value` (`_common.as_utc`).
3. Load an optional driver with `import_driver(module, extra)` inside `__init__`, and add the extra to `pyproject.toml`.
4. Decorate the class with `@register_data_source` and import the module in `registration.register_all()`.
5. Add unit tests with a fake driver (`tests/unit/datasources/fakes.py`) and a backend to `tests/integration/test_adapter_contract.py`, so the new engine is held to the same contract as the others.

## Tests

- `tests/unit/datasources/`: the registry, `${VAR}` expansion, the shared SQL base, and each adapter's config parsing, type mapping and generated queries (using fake drivers, so no account or server is needed).
- `tests/integration/test_adapter_contract.py`: loads the same four rows into every reachable backend and checks every adapter gives the same answers: row count, nulls (including missing MongoDB fields), distinct values excluding nulls, max values, UTC timestamps, canonical column types, and an empty dataset. DuckDB, Postgres, MySQL and MongoDB run locally with `docker compose up -d` and always in CI. Snowflake and BigQuery run when `SENTINEL_TEST_SNOWFLAKE_URL` / `SENTINEL_TEST_BIGQUERY_URL` are set.
