# Configuration: Datasets and Policies

**Location:** `src/sentinel/config_loading.py`, `src/sentinel/policy_loader/`, `src/sentinel/dataset_loader/`, `src/sentinel/cli/resolution.py`
**Depends on:** `domain`
**Used by:** `cli`

Each validated dataset is described by two YAML files with the same base name:

```text
datasets/orders.yaml   # where the data lives and how important it is
policies/orders.yaml   # what "good data" means for it
```

`sentinel validate orders` finds both by that naming convention.

---

## Dataset file

```yaml
id: orders                       # stable key for all history
name: orders                     # display name; `sentinel history` uses this
source_type: duckdb              # duckdb | postgres
environment: local
owner: data-platform-team
criticality: high                # low | medium | high | critical
config_reference: data/orders.csv
```

`config_reference` is interpreted by the adapter named in `source_type`:

| `source_type` | `config_reference` |
|---|---|
| `duckdb` | Path to a CSV file, relative to the working directory |
| `postgres` | `postgresql://user:password@host:5432/dbname?table=orders` |

## Policy file

```yaml
dataset: orders
version: "2026-10-01"            # optional; defaults to "unversioned"
rules:
  - name: row_count              # unique within the policy; also the history key
    type: row_count
    threshold:
      strategy: static
      min: 1000

  - name: customer_id_not_null
    type: null_rate
    column: customer_id
    severity: high               # info | warning (default) | high | critical
    blocking: true               # default true
    threshold:
      strategy: static
      max: 0.01

  - name: unique_order_id
    type: uniqueness
    column: order_id
    threshold:
      strategy: static
      max: 0

  - name: orders_freshness
    type: freshness
    column: updated_at
    threshold:
      strategy: static
      max: 60                    # minutes

  - name: orders_schema
    type: schema
    expected_schema:
      order_id: integer
      customer_id: string
      order_total: decimal
      updated_at: timestamp
    threshold:
      strategy: static
      max: 0                     # number of schema differences allowed
```

Every key under `threshold` other than `strategy` is passed to the strategy as a parameter. See [Rules](rules.md) for what each rule measures and [Threshold Strategies](thresholds.md) for each strategy's parameters.

> **Rule names are history keys.** Renaming a rule starts its history over, which affects adaptive thresholds and failure-frequency scoring. Change the threshold or strategy freely; keep the name stable.

---

## Loading

```text
resolve_policy("orders")
  └─ Path($SENTINEL_POLICIES_DIR or "policies") / "orders.yaml"
       └─ load_policy(path)
            └─ load_yaml_model(path, Policy, PolicyLoadError)
```

`config_loading.load_yaml_model()` is shared by both loaders. It:

1. reads the file
2. parses it with `yaml.safe_load`
3. rejects an empty file or a non-mapping top level
4. validates the result against the pydantic model

Every failure is re-raised as the caller's error type with the file path in the message:

| Error | Raised by |
|---|---|
| `PolicyLoadError` | `policy_loader.load_policy` |
| `DatasetLoadError` | `dataset_loader.load_dataset` |

Messages include the file path and, for validation failures, pydantic's field-level explanation. Both errors abort the run before any data is read.

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `SENTINEL_DATASETS_DIR` | `datasets` | Directory searched for `<name>.yaml` dataset files |
| `SENTINEL_POLICIES_DIR` | `policies` | Directory searched for `<name>.yaml` policy files |
| `SENTINEL_DATABASE_URL` | `postgresql://sentinel:sentinel@localhost:5432/sentinel` | Sentinel's Postgres store (see [Persistence](persistence.md)) |

Paths are relative to the current working directory.

---

## Design notes

- **Why the file lookup lives in `cli/`.** "Where config files live" is a concern of one entry point. The loaders take a path, so another entry point (an API, a scheduler) can locate files differently and reuse them unchanged.
- **Why a filesystem convention instead of a registry.** Policies live in version control next to pipeline code, so changes are reviewed and their history is kept by git. A database-backed registry would be the next step if teams need to register datasets without sharing a repository.
- **Why `params` is an open dict.** New strategies bring new parameters. Validating them centrally would mean editing the domain model for every strategy. Each strategy validates its own instead.

## Tests

- `tests/unit/policy_loader/`, `tests/unit/dataset_loader/`: valid files, malformed YAML, schema violations
- `tests/unit/cli/test_resolution.py`: directory resolution and environment overrides
- `tests/fixtures/policies/malformed_*.yaml`, `tests/fixtures/datasets/malformed_*.yaml`: the failure fixtures
