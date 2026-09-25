"""Pure-function tests for sentinel.observability.health -- no duckdb, no
persistence, no fixtures: every case here is plain Python values in,
plain Python values out, matching the "logic separate from I/O"
discipline the module's own docstring describes."""

from __future__ import annotations

import pytest

from sentinel.domain.incident import IncidentPriority
from sentinel.observability.health import (
    classify_recurrence,
    derive_dataset_health,
    highest_priority,
)
from sentinel.observability.views import DatasetHealth, RecurrenceClassification


def test_highest_priority_of_empty_sequence_is_none() -> None:
    assert highest_priority(()) is None


def test_highest_priority_picks_the_most_severe() -> None:
    priorities = [IncidentPriority.INFO, IncidentPriority.CRITICAL, IncidentPriority.WARNING]
    assert highest_priority(priorities) is IncidentPriority.CRITICAL


def test_highest_priority_of_a_single_value_is_itself() -> None:
    assert highest_priority([IncidentPriority.HIGH]) is IncidentPriority.HIGH


def test_dataset_health_with_no_runs_ever_is_unknown() -> None:
    assert derive_dataset_health(has_any_run=False, incident_priorities_on_latest_run=()) is (
        DatasetHealth.UNKNOWN
    )


def test_dataset_health_with_no_incidents_on_latest_run_is_healthy() -> None:
    assert derive_dataset_health(has_any_run=True, incident_priorities_on_latest_run=()) is (
        DatasetHealth.HEALTHY
    )


@pytest.mark.parametrize("priority", [IncidentPriority.WARNING, IncidentPriority.HIGH])
def test_dataset_health_is_degraded_for_warning_or_high(priority: IncidentPriority) -> None:
    assert derive_dataset_health(
        has_any_run=True, incident_priorities_on_latest_run=[priority]
    ) is DatasetHealth.DEGRADED


def test_dataset_health_is_critical_for_a_critical_incident() -> None:
    assert derive_dataset_health(
        has_any_run=True, incident_priorities_on_latest_run=[IncidentPriority.CRITICAL]
    ) is DatasetHealth.CRITICAL


def test_dataset_health_takes_the_highest_of_several_incidents_on_one_run() -> None:
    priorities = [IncidentPriority.WARNING, IncidentPriority.CRITICAL, IncidentPriority.INFO]
    assert derive_dataset_health(
        has_any_run=True, incident_priorities_on_latest_run=priorities
    ) is DatasetHealth.CRITICAL


def test_dataset_health_ignores_info_priority_incidents() -> None:
    """An INFO-priority incident on the latest run shouldn't degrade
    health any more than Milestone 5 judged it worth escalating."""
    assert derive_dataset_health(
        has_any_run=True, incident_priorities_on_latest_run=[IncidentPriority.INFO]
    ) is DatasetHealth.DEGRADED


def test_recurrence_is_first_occurrence_for_a_single_failure() -> None:
    assert classify_recurrence(failure_count=1, most_recent_evaluation_failed=True) is (
        RecurrenceClassification.FIRST_OCCURRENCE
    )


def test_recurrence_is_first_occurrence_even_if_zero_failures_somehow_reported() -> None:
    """Defensive floor: classify_recurrence is only ever called for pairs
    that appeared in a failure-count aggregate (so failure_count >= 1 in
    practice), but 0 shouldn't crash or be misclassified as RECURRING."""
    assert classify_recurrence(failure_count=0, most_recent_evaluation_failed=False) is (
        RecurrenceClassification.FIRST_OCCURRENCE
    )


def test_recurrence_is_recurring_when_two_or_more_failures_but_now_passing() -> None:
    assert classify_recurrence(failure_count=2, most_recent_evaluation_failed=False) is (
        RecurrenceClassification.RECURRING
    )


def test_recurrence_is_persistent_when_still_failing() -> None:
    assert classify_recurrence(failure_count=3, most_recent_evaluation_failed=True) is (
        RecurrenceClassification.PERSISTENT
    )


def test_recurrence_boundary_at_exactly_two_failures() -> None:
    """2 is the milestone's own stated boundary ('more than once') --
    exactly 2, still passing now, must already read as RECURRING, not
    require a 3rd failure first."""
    assert classify_recurrence(failure_count=2, most_recent_evaluation_failed=False) is (
        RecurrenceClassification.RECURRING
    )
