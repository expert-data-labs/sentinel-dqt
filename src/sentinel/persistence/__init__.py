"""Sentinel's own persistence store: durable operational history of
validation runs, metrics, and quality events (FR-06/07/08).

For this milestone this is a DuckDB-backed embedded database — a
deliberate, named trade-off ahead of SQLAlchemy + PostgreSQL (see
docs/architecture/0003-milestone-2-architecture.md Part 3). This is a
different DuckDB database from sentinel.datasources.duckdb_source, which
queries the dataset *being validated*, not Sentinel's own history.
"""
