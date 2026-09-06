# Sentinel — Documentation

This folder holds Sentinel's architecture decision records (ADRs) — one file per milestone, written and approved before that milestone's implementation begins, then left in place as the record of what was decided and why. Each one documents the problem as understood at the time, the alternatives considered, and a decisions log at the end; later milestones amend the design going forward rather than editing history, so an earlier ADR can describe a decision a later one changes.

For day-to-day setup and usage (installing dependencies, running tests, Docker), see the [root README](../README.md).

## Architecture Decision Records

- [`architecture/0001-milestone-0-architecture.md`](architecture/0001-milestone-0-architecture.md) — Milestone 0 (Architecture & Foundation): the domain split between config-time definitions and run-time facts, the Domain-Oriented Modular Architecture (undersized), the four core interfaces (`Rule`, `ThresholdStrategy`, `DataSource`, the orchestrator), and the repository layout.
- [`architecture/0002-milestone-1-architecture.md`](architecture/0002-milestone-1-architecture.md) — Milestone 1 (Functional Core): the three concrete rules (row count, null rate, uniqueness), the static threshold strategy, and the explicit registration wiring that connects them to Milestone 0's registries.
- [`architecture/0003-milestone-2-architecture.md`](architecture/0003-milestone-2-architecture.md) — Milestone 2 (CLI & Persistence): `sentinel validate`/`sentinel history`, a `DuckDBSource` data source adapter pulled forward from Milestone 3, DuckDB-backed persistence as a named interim trade-off ahead of SQLAlchemy + PostgreSQL, and the blocking-aware exit code Milestone 0 left as an open question.
- [`architecture/0004-milestone-3-architecture.md`](architecture/0004-milestone-3-architecture.md) — Milestone 3 (Additional Rules & Adapters), **implemented**: the Freshness and Schema Validation rules, a new `DataSource.columns()` method, the `RuleConfig.expected_schema` and `Metric.details` additions, and the `PostgresDataSource` adapter, with cross-adapter integration tests proving Rules are backend-independent — written but not yet confirmed by a local `uv sync && pytest` run.
