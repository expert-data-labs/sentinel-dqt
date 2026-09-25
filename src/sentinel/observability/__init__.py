"""Observability (Milestone 6): read-only queries over Sentinel's
persisted runtime facts, presented as dashboard-ready views. See
docs/architecture/0007-milestone-6-design.md for the full design.

Deliberately does NOT re-export ``ObservabilityQueryService`` or
``TimeWindow`` here -- those live in ``sentinel.observability.queries``,
which imports ``duckdb``, and a package ``__init__`` re-exporting it would
force every consumer of this package's duckdb-free vocabulary (``views``,
``health``) to have duckdb importable too, defeating the whole point of
keeping ``health.py`` "no duckdb import, testable with zero I/O." No
existing package in this codebase re-exports its own duckdb-touching
concrete classes through an ``__init__.py`` either --
``DuckDBHistoricalMetricsSource``/``DuckDBFailureHistorySource`` are
always imported directly from their own ``persistence.*`` submodules,
never through ``sentinel.persistence.__init__`` -- so this follows the
same precedent: import ``ObservabilityQueryService``/``TimeWindow``
directly from ``sentinel.observability.queries``.
"""

from __future__ import annotations

from sentinel.observability.health import (
    classify_recurrence,
    derive_dataset_health,
    highest_priority,
)
from sentinel.observability.views import (
    DatasetHealth,
    DatasetHealthView,
    FailedRuleView,
    IncidentHistoryEntry,
    MetricTrendPoint,
    QualityHistoryEntry,
    RecurrenceClassification,
    RecurringFailureView,
)

__all__ = [
    "DatasetHealth",
    "DatasetHealthView",
    "FailedRuleView",
    "IncidentHistoryEntry",
    "MetricTrendPoint",
    "QualityHistoryEntry",
    "RecurrenceClassification",
    "RecurringFailureView",
    "classify_recurrence",
    "derive_dataset_health",
    "highest_priority",
]
