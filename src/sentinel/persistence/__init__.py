"""Sentinel's own store for run history: runs, metrics, quality events, incidents.

Backed by an embedded DuckDB file. This is separate from duckdb_source, which
reads the dataset being validated.
"""
