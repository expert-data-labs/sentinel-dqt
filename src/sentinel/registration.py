"""Bootstraps the Rule Engine, Threshold Engine, and DataSource registry
by importing every concrete implementation Milestone 1, 2, and 4 ship,
which is what actually triggers their ``@register_rule`` /
``@register_threshold_strategy`` / ``@register_data_source`` decorators.

Nothing else in the package imports ``sentinel.rules.row_count`` (or its
siblings) — so without this, none of these concrete implementations would
ever be registered in a process that doesn't otherwise happen to import
them, and a caller doing ``get_rule("row_count")`` would hit
``RuleNotRegisteredError`` even though the class exists on disk.

This is deliberately an explicit function, not a side effect of importing
``sentinel.rules``/``sentinel.thresholds``/``sentinel.datasources``
themselves: it makes "when does registration happen" a visible, callable
fact rather than something baked into package import order. Every real
entry point — Milestone 1's end-to-end integration test, Milestone 2's
CLI startup — calls this once before resolving anything by its registry
key.

Safe to call more than once: Python caches modules in ``sys.modules``, so
a second call just re-imports already-loaded modules rather than
re-running their registration decorators. It never trips the registries'
"already registered" guard.
"""

from __future__ import annotations


def register_all() -> None:
    """Import every concrete Rule, ThresholdStrategy, and DataSource
    implementation, registering each one under its ``rule_type`` /
    ``strategy_type`` / ``source_type``."""
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
        statistical,
        static,
    )
