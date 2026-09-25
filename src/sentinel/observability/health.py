"""Pure derivation logic for the observability layer (Milestone 6): what
counts as DEGRADED, what counts as recurring -- with no duckdb import, no
I/O, and no dependency on sentinel.observability.queries.

Kept separate from queries.py for the same reason
sentinel.prioritization.scoring's ``*_score()`` functions are kept
separate from IncidentPrioritizer's orchestration: the *rules* for "what
does this data mean" should be testable against plain Python values,
independent of whatever fetched those values. queries.py's job is only to
fetch the right rows and hand them to the functions here.
"""

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
    """The most severe of a set of incident priorities, or ``None`` for an
    empty sequence (a run with no incidents -- everything passed -- has no
    "highest priority" to report). Mirrors
    sentinel.orchestration.orchestrator's own ``_worst_status`` in shape,
    but over IncidentPriority rather than Status -- a deliberately
    separate function rather than a shared generic "worst of" helper,
    since the two vocabularies live in different layers and reusing one
    ranking table for both would be exactly the kind of conflation
    Milestone 5 was built to avoid."""
    if not priorities:
        return None
    return max(priorities, key=lambda priority: _PRIORITY_RANK[priority])


def derive_dataset_health(
    has_any_run: bool,
    incident_priorities_on_latest_run: Sequence[IncidentPriority],
) -> DatasetHealth:
    """Dataset Health, derived from the dataset's LATEST validation run
    only (docs/architecture/0007-milestone-6-design.md Part 6) -- a
    "right now" answer, not a windowed aggregate (Recurring Failures
    already covers the historical question).

    ``has_any_run=False`` means no validation run has ever been recorded
    for this dataset -- UNKNOWN, deliberately not folded into HEALTHY,
    since "never checked" and "checked and passed" are different claims.

    Driven by IncidentPriority, not raw Status: a FAIL event Milestone 5
    judged low-priority (e.g. a first-occurrence failure on a
    low-criticality dataset) shouldn't degrade a dataset's health any more
    than Milestone 5 judged it should raise an alarm -- using Status here
    would re-flatten exactly what Milestone 5 was built to avoid.
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
    """Recurring Failures classification for one (dataset, rule) pair
    within a selected time window (docs/architecture/0007-milestone-6-
    design.md Part 7).

    ``failure_count`` is the number of non-PASS QualityEvents for this
    pair within the window (1 = first occurrence, 2+ = recurring).
    ``most_recent_evaluation_failed`` answers a different question than
    the window itself: is the single most recent time this rule was ever
    evaluated (which may or may not be the same event that made
    ``failure_count`` non-zero) ALSO a failure -- i.e. is this pair still
    actively broken right now, not just historically frequent. A pair
    that failed often last week but has since started passing again is
    RECURRING, not PERSISTENT.
    """
    if failure_count <= 1:
        return RecurrenceClassification.FIRST_OCCURRENCE
    if most_recent_evaluation_failed:
        return RecurrenceClassification.PERSISTENT
    return RecurrenceClassification.RECURRING
