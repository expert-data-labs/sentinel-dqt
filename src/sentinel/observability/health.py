"""Pure rules for dataset health and failure recurrence (no I/O)."""

from __future__ import annotations

from collections.abc import Sequence

from sentinel.domain import IncidentPriority
from sentinel.observability.views import DatasetHealth, RecurrenceClassification

_PRIORITY_RANK: dict[IncidentPriority, int] = {
    IncidentPriority.INFO: 0,
    IncidentPriority.WARNING: 1,
    IncidentPriority.HIGH: 2,
    IncidentPriority.CRITICAL: 3,
}


def highest_priority(priorities: Sequence[IncidentPriority]) -> IncidentPriority | None:
    """Most severe priority, or None if there are none."""
    if not priorities:
        return None
    return max(priorities, key=lambda priority: _PRIORITY_RANK[priority])


def derive_dataset_health(
    has_any_run: bool,
    incident_priorities_on_latest_run: Sequence[IncidentPriority],
) -> DatasetHealth:
    """Dataset health from its latest run only.

    - no runs: UNKNOWN
    - no incidents: HEALTHY
    - any CRITICAL incident: CRITICAL
    - otherwise: DEGRADED

    Based on incident priority, not raw status, so low-priority failures don't
    raise alarms.
    """
    if not has_any_run:
        return DatasetHealth.UNKNOWN
    if not incident_priorities_on_latest_run:
        return DatasetHealth.HEALTHY
    highest = highest_priority(incident_priorities_on_latest_run)
    if highest is IncidentPriority.CRITICAL:
        return DatasetHealth.CRITICAL
    return DatasetHealth.DEGRADED


def classify_recurrence(
    failure_count: int,
    most_recent_evaluation_failed: bool,
) -> RecurrenceClassification:
    """Classify a rule's failures within a time window.

    - 0 or 1 failure: FIRST_OCCURRENCE
    - 2+ and the latest evaluation (ever) failed: PERSISTENT
    - 2+ but now passing again: RECURRING
    """
    if failure_count <= 1:
        return RecurrenceClassification.FIRST_OCCURRENCE
    if most_recent_evaluation_failed:
        return RecurrenceClassification.PERSISTENT
    return RecurrenceClassification.RECURRING
