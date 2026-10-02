"""Sentinel's own store for run history: runs, metrics, quality events, incidents.

Backed by Postgres (SENTINEL_DATABASE_URL), shared by all teams and processes.
Schema changes go through Alembic migrations (``sentinel db upgrade``). This is
separate from the data sources, which read the datasets being validated.
"""
