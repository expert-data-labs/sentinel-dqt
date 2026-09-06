from __future__ import annotations

from sentinel.domain import Status
from sentinel.prioritization.frequency import summarize


def test_empty_outcomes_is_first_occurrence() -> None:
    """Edge case: zero historical observations."""
    history = summarize(())
    assert history.occurrences == 0
    assert history.total_observations == 0
    assert history.consecutive_failures == 0
    assert history.is_first_occurrence is True
    assert history.frequency_rate == 0.0


def test_all_passes_is_first_occurrence() -> None:
    """A rule that has always passed before: this is its first-ever
    failure, even though it has plenty of observation history (Scenario 7:
    a first-time failure should not be treated as recurring)."""
    history = summarize([Status.PASS, Status.PASS, Status.PASS])
    assert history.occurrences == 0
    assert history.is_first_occurrence is True
    assert history.consecutive_failures == 0


def test_warn_counts_as_an_occurrence_same_as_fail() -> None:
    history = summarize([Status.WARN, Status.PASS])
    assert history.occurrences == 1
    assert history.is_first_occurrence is False


def test_consecutive_failures_counts_the_leading_streak() -> None:
    """Outcomes are most-recent-first: a streak of failures immediately
    preceding now, broken by an older PASS."""
    history = summarize([Status.FAIL, Status.FAIL, Status.FAIL, Status.PASS, Status.FAIL])
    assert history.consecutive_failures == 3
    assert history.occurrences == 4
    assert history.total_observations == 5


def test_consecutive_failures_is_zero_when_the_most_recent_outcome_passed() -> None:
    history = summarize([Status.PASS, Status.FAIL, Status.FAIL])
    assert history.consecutive_failures == 0
    assert history.occurrences == 2


def test_every_outcome_a_failure_is_the_full_streak() -> None:
    history = summarize([Status.FAIL, Status.FAIL, Status.FAIL])
    assert history.consecutive_failures == 3
    assert history.is_first_occurrence is False


def test_frequency_rate_is_occurrences_over_total_observations() -> None:
    history = summarize([Status.FAIL, Status.PASS, Status.FAIL, Status.PASS])
    assert history.occurrences == 2
    assert history.total_observations == 4
    assert history.frequency_rate == 0.5


def test_frequency_rate_does_not_divide_by_zero_when_empty() -> None:
    assert summarize(()).frequency_rate == 0.0
