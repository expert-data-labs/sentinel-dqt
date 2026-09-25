# Sentinel

A configurable data reliability and threshold intelligence platform. Sentinel separates data
quality policy (what "good data" means for a dataset) from pipeline implementation, so teams
declare expectations in configuration and Sentinel handles execution, threshold evaluation,
historical context, and incident prioritization.

**Status:** Milestones 0-6 complete. The domain model, the three pluggable interfaces (Rule,
ThresholdStrategy, DataSource), a CLI, DuckDB and Postgres-backed persistence, and concrete Rule
and ThresholdStrategy implementations are all in place and tested. Milestone 4 adds
historical-metrics-aware ("adaptive") threshold strategies -- Percentage Deviation, Statistical
(Mean/StdDev), Median/MAD, and Seasonal Baseline -- alongside the original static thresholds, plus
a synthetic evaluation framework (`experiments/threshold_intelligence/`) that measures each
strategy's false-positive/false-negative behavior against controlled synthetic scenarios.
Milestone 5 turns a non-passing validation into an explainable, prioritized `Incident`
(INFO/WARNING/HIGH/CRITICAL) by combining validation severity, dataset criticality, deviation
magnitude, historical failure frequency, and anomaly confidence into one deterministic, weighted
score -- deliberately no ML, microservices, or external incident-management integrations.
Milestone 6 adds a read-only Observability layer: a new `ObservabilityQueryService` (Dataset
Health, Quality History, Metric Trends, Failed Rules, Incident History, Recurring Failures), two
additive schema changes so `Incident` and each threshold's computed bounds are now persisted, and
a single-file Streamlit dashboard (`dashboard/app.py`) that reads only through that query service
-- Observability never reimplements validation, threshold, or prioritization logic.

See `docs/architecture/0007-milestone-6-design.md` for the Milestone 6 design, engineering
analysis, and verification notes, `docs/architecture/0006-milestone-5-design.md` for the
Milestone 5 design, `docs/architecture/0005-milestone-4-design.md` for the Milestone 4 design and
findings (including a "Definition of Done" section answering when each strategy is and isn't
appropriate), `docs/experiments/milestone-4-results.md` for the raw results, and
`docs/architecture/0001-milestone-0-architecture.md` onward for the earlier milestones' approved
architecture.

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
- `src/sentinel/observability/` — read-only query layer for the dashboard (`ObservabilityQueryService`,
  read models in `views.py`, pure Dataset-Health/Recurring-Failure derivation in `health.py`).
  Consumes already-persisted runtime facts only; never reimplements validation/threshold/
  prioritization logic.
- `dashboard/app.py` — a single-file Streamlit app reading only through `ObservabilityQueryService`.
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

## Running the dashboard (Milestone 6)

```bash
uv sync --group dashboard
uv run streamlit run dashboard/app.py
```

`streamlit` is its own optional dependency group, separate from `dependencies`/`dev` -- `sentinel
validate`/`sentinel history` users don't need a web framework installed. The dashboard is entirely
read-only and reads only through `ObservabilityQueryService`; run `sentinel validate` a few times
first so there's history for it to show.

## Local Postgres (Milestone 3)

`PostgresDataSource`'s tests need a real Postgres to run against. Start one with:

```bash
docker compose up -d
```

This brings up a `postgres:16-alpine` container on `localhost:5432` (db/user/password all
`sentinel`) — the same credentials CI's own ephemeral Postgres service container uses, so
`SENTINEL_TEST_POSTGRES_DSN=postgresql://sentinel:sentinel@localhost:5432/sentinel` works
identically in both places. See `docker-compose.yml` and `.github/workflows/ci.yml`.
