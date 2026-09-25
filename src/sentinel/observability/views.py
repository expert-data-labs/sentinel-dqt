"""Presentation-shaped read models for the observability layer (Milestone 6).

These are deliberately NOT domain objects reused as DTOs -- see
docs/architecture/0007-milestone-6-design.md Part 5. A Dataset, a
ValidationRun, a QualityEvent, an Incident each mean something precise in
the domain; a dashboard row means "what should render in this cell",
which is a different concern with a different lifecycle (add a column to
a table without touching domain code). Every view here is a frozen
dataclass built by sentinel.observability.queries.ObservabilityQueryService
from plain query results -- nothing here imports duckdb, and nothing in
the domain package imports these.

``DatasetHealth`` and ``RecurrenceClassification`` are observability-layer
vocabulary, not domain vocabulary (contrast ``IncidentPriority``, which
*is* a domain concept, computed by sentinel.prioritization and consumed
here read-only) -- Sentinel's domain has no notion of "dataset health" or
"recurring", only of Metrics, QualityEvents, and Incidents. Both live here,
next to the views that carry them, mirroring where Status/Severity live
in domain/events.py next to the objects that carry them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DatasetHealth(StrEnum):
    """A dataset's current, point-in-time health (Milestone 6) -- derived
    from its LATEST validation run only, not a windowed aggregate (see
    sentinel.observability.health.derive_dataset_health). Distinct from
    Status and IncidentPriority: Status is per-event, IncidentPriority is
    per-incident, DatasetHealth is the one summary answer "does this
    dataset need attention right now" for an entire dataset."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class RecurrenceClassification(StrEnum):
    """How a (dataset, rule) pair's failures within a selected time window
    should be read -- see sentinel.observability.health.classify_recurrence
    and docs/architecture/0007-milestone-6-design.md Part 7 for the exact
    definitions."""

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
    """One observed point of the Metric Trends view. ``threshold_details``
    is the JSON-encoded baseline/bounds the threshold strategy computed at
    validation time (``QualityEvent.threshold_details``, persisted to
    ``quality_events.details`` as of Milestone 6) -- read back verbatim,
    never recomputed here."""

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
