"""Registers every built-in Rule, ThresholdStrategy and DataSource.

Importing a module runs its ``@register_*`` decorator. Entry points (CLI, tests)
call ``register_all()`` once before looking anything up. Safe to call more than
once.
"""

from __future__ import annotations


def register_all() -> None:
    """Import all built-in implementations so they register themselves."""
    from sentinel.datasources import duckdb_source, postgres_source  # noqa: F401
    from sentinel.rules import (  # noqa: F401
        freshness,
        null_rate,
        row_count,
        schema_validation,
        uniqueness,
    )
    from sentinel.thresholds import (  # noqa: F401
        median_mad,
        percentage_deviation,
        seasonal,
        static,
        statistical,
    )
