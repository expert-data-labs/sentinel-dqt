# Command-Line Interface

**Location:** `src/sentinel/cli/`, `src/sentinel/registration.py`
**Depends on:** every other package (the CLI is the composition root)
**Entry point:** `sentinel = "sentinel.cli.main:app"` (Typer)

The CLI is how pipelines call Sentinel. It is also the **composition root**: the one place where concrete implementations are chosen and connected to each other.

| File | Role |
|---|---|
| `cli/main.py` | `validate` and `history` commands, exit-code logic, summary output |
| `cli/bootstrap.py` | `build_context()`: registers plug-ins, opens the store, ensures the schema |
| `cli/resolution.py` | `resolve_dataset(name)`, `resolve_policy(name)`: the file lookup convention |
| `registration.py` | `register_all()`: imports every concrete rule, strategy and adapter so their decorators run |

---

## `sentinel validate <dataset>`

Runs the dataset's policy, persists the result and reports it.

```bash
sentinel validate orders
```

Sequence:

1. `build_context()` calls `register_all()`, opens a store connection, and checks the store is at the latest migration (exit `3` if not).
2. `resolve_dataset("orders")` and `resolve_policy("orders")` load and validate both YAML files.
3. `get_data_source(dataset.source_type, dataset.config_reference)` builds the adapter.
4. `validate_and_record(conn, dataset, policy, source)` takes the dataset's run lock, runs `ValidationOrchestrator` (with the Postgres history sources on the same connection), writes the run, and releases the lock. A concurrent `validate` of the same dataset waits; other datasets run in parallel.
5. A summary is printed and the process exits with the computed code.

### Output

The summary has one line per rule, plus a priority line for each rule that did not pass. Illustrative output from a first run against the bundled `orders` sample (abridged):

```text
Dataset: orders
Run ID:  6f0c2a8e-1d3b-4e5f-9a7c-2b8d4e6f1a3c
Result:  FAIL (blocking)

  ✗ row_count  actual=12  expected: row_count >= 1000
      priority=WARNING score=49.9  Dataset criticality: HIGH
  ✗ customer_id_not_null  actual=0.08333  expected: customer_id_not_null <= 0.01
      priority=HIGH score=60.0  Dataset criticality: HIGH
  ✗ unique_order_id  actual=1  expected: unique_order_id <= 0
      priority=HIGH score=60.0  Dataset criticality: HIGH
  ...
```

Every rule's true status is shown, whether or not it is blocking.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | No blocking rule failed and nothing warned. Non-blocking failures may still exist; they are printed and persisted. |
| `1` | A rule warned and no blocking rule failed. |
| `2` | At least one rule with `blocking: true` failed. |

The exit code is a separate judgement from `ValidationRun.status`, which records the worst status regardless of `blocking`. A run can therefore be stored as FAIL while the pipeline continues with exit code 0.

**Execution errors** are things like a malformed policy, an unknown rule type, an unreachable database or insufficient history for an adaptive strategy. They are not caught. Python prints a traceback and exits non-zero (code `1`), and nothing is persisted for that run. The built-in threshold strategies only return PASS or FAIL, so with them, exit code `1` in practice means an execution error. Treat every non-zero code as "do not proceed".

### Using it in a pipeline

```bash
# Airflow BashOperator, cron, Makefile, CI step...
sentinel validate orders || exit $?
```

Any orchestrator that fails a task on a non-zero exit code will stop downstream tasks when a blocking rule fails.

---

## `sentinel history <dataset> [--limit N]`

Shows recent runs from the store, newest first (default limit 10). Illustrative output:

```text
Dataset: orders

  2026-10-01T06:00:12+00:00  FAIL  run=6f0c2a8e-...  failed: customer_id_not_null, row_count, unique_order_id
  2026-09-30T06:00:09+00:00  PASS  run=0b7e91d4-...
```

The `failed:` list shows rules with status FAIL. Note that `history` looks datasets up by the dataset's `name`, while `validate` uses the YAML file name. Keep the two the same.

---

## Environment variables

| Variable | Default | Used for |
|---|---|---|
| `SENTINEL_DATABASE_URL` | `postgresql://sentinel:sentinel@localhost:5432/sentinel` | Sentinel's Postgres store |
| `SENTINEL_DATASETS_DIR` | `datasets` | Dataset YAML lookup |
| `SENTINEL_POLICIES_DIR` | `policies` | Policy YAML lookup |

## Why registration is explicit

Implementations register themselves with a decorator, but a decorator only runs when its module is imported, and nothing else imports `rules/null_rate.py`. `register_all()` makes "when does registration happen" a visible function call instead of a side effect of import order. It is safe to call more than once, because Python caches modules.

## Tests

`tests/integration/test_cli.py` runs `validate` and `history` through Typer's test runner against temporary stores. `tests/integration/test_end_to_end.py` runs the real policy loader, `register_all()`, real rules and the static strategy through the orchestrator, against a `FakeDataSource` seeded from the fixture CSV.
