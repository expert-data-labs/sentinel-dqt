"""Read models for the dashboard. Frozen dataclasses, separate from domain objects.

DatasetHealth and RecurrenceClassification are dashboard vocabulary, not domain
concepts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DatasetHealth(StrEnum):
    """A dataset's health based on its latest run."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class RecurrenceClassification(StrEnum):
    """How to read a rule's failures within a time window."""

    FIRST_OCCURRENCE = "first_occurrence"
    RECURRING = "recurring"
    PERSISTENT = "persistent"


@dataclass(frozen=True)
class DatasetHealthView:
    """One row of the Dataset Health view."""

    dataset_id: str
    dataset_name: str
    health: DatasetHealth
    latest_validation_at: datetime | None
    latest_run_status: str | None
    highest_incident_priority: str | None
    failed_rules: int


@dataclass(frozen=True)
class QualityHistoryEntry:
    """One row of the Quality History view, for one dataset."""

    run_id: uuid.UUID
    started_at: datetime
    rules_evaluated: int
    rules_failed: int
    overall_status: str
    highest_incident_priority: str | None


@dataclass(frozen=True)
class MetricTrendPoint:
    """One point on a metric trend.

    ``threshold_details`` is the stored baseline/bounds JSON from validation
    time.
    """

    computed_at: datetime
    value: float
    threshold_details: str | None


@dataclass(frozen=True)
class FailedRuleView:
    """One row of the Failed Rules view: one (dataset, rule) pair."""

    dataset_id: str
    rule_name: str
    failure_count: int
    latest_failure_at: datetime
    current_priority: str | None


@dataclass(frozen=True)
class IncidentHistoryEntry:
    """One row of the Incident History view: one persisted Incident."""

    incident_id: uuid.UUID
    occurred_at: datetime
    dataset_id: str
    rule_name: str
    priority: str
    score: float
    top_reason: str | None


@dataclass(frozen=True)
class RecurringFailureView:
    """One row of the Recurring Failures view: one (dataset, rule) pair."""

    dataset_id: str
    rule_name: str
    failure_count: int
    last_seen_at: datetime
    classification: RecurrenceClassification
