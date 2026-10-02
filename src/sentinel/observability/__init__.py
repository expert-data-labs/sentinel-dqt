"""Observability: read-only dashboard views over Sentinel's stored history.

ObservabilityQueryService and TimeWindow are not re-exported here because they
import duckdb; import them from ``sentinel.observability.queries``.
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
