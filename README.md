# Sentinel

A configurable data reliability and threshold intelligence platform. Sentinel separates data
quality policy (what "good data" means for a dataset) from pipeline implementation, so teams
declare expectations in configuration and Sentinel handles execution, threshold evaluation,
historical context, and incident prioritization.

**Status:** Milestone 0 (architecture and foundation) complete. The domain model, the three
pluggable interfaces (Rule, ThresholdStrategy, DataSource) with their registries, the policy
loader, and the ValidationOrchestrator that wires them together are all in place and tested — but
no concrete Rule, ThresholdStrategy, or DataSource implementation exists yet. Running a real policy
against real data is Milestone 1's job.

See `docs/architecture/0001-milestone-0-architecture.md` for the approved architecture: problem
decomposition, domain model, interface contracts, and the reasoning behind each decision.

## Project layout

- `src/sentinel/domain/` — config-time definitions (`Policy`, `RuleConfig`, `ThresholdConfig`,
  `Dataset`) and run-time facts (`Metric`, `QualityEvent`, `ValidationRun`). No behavior, only
  structure — pydantic models at the external-input boundary, frozen dataclasses for facts.
- `src/sentinel/rules/`, `src/sentinel/thresholds/`, `src/sentinel/datasources/` — the `Rule`,
  `ThresholdStrategy`, and `DataSource` Protocols, each with a small dict-based registry. Empty of
  concrete implementations until Milestone 1.
- `src/sentinel/orchestration/` — `ValidationOrchestrator`, which runs a Policy's rules against a
  Dataset's DataSource and assembles the outcome as a `ValidationRun`.
- `src/sentinel/policy_loader/` — reads a policy YAML file into a validated `Policy`.
- `src/sentinel/cli/` — empty stub; the CLI arrives in Milestone 2.
- `tests/` — mirrors `src/sentinel/`. `tests/fixtures/policies/orders.yaml` is the PRD's example
  policy; `tests/fixtures/data/orders.csv` is a small sample dataset for Milestone 1's rule tests —
  nothing reads it yet, since there's no DuckDB adapter to load it with.
- `tests/unit/doubles.py` — shared fakes (`FakeDataSource`, `DummyRule`, `DummyThresholdStrategy`)
  used across the test suite instead of real implementations.

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
```

## Running in Docker

```bash
docker build -t sentinel .
docker run --rm sentinel
```

The image installs dependencies with uv and runs the test suite by default. There's nothing to
serve yet — no CLI or API exists before Milestone 2 — so this is for reproducing the test run
locally, not for deployment.
