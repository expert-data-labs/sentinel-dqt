"""Summarizes a rule's past outcomes into a FailureHistory."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sentinel.domain import Status


@dataclass(frozen=True)
class FailureHistory:
    """Summary of a rule's past outcomes.

    ``occurrences`` counts WARN and FAIL. ``consecutive_failures`` is the
    current non-PASS streak before this run (this run not included).
    """

    occurrences: int
    total_observations: int
    consecutive_failures: int
    is_first_occurrence: bool

    @property
    def frequency_rate(self) -> float:
        if self.total_observations == 0:
            return 0.0
        return self.occurrences / self.total_observations


def summarize(outcomes: Sequence[Status]) -> FailureHistory:
    """Summarize outcomes (most recent first) into a FailureHistory.

    No outcomes means a first occurrence.
    """
    occurrences = sum(1 for status in outcomes if status is not Status.PASS)

    consecutive_failures = 0
    for status in outcomes:
        if status is Status.PASS:
            break
        consecutive_failures += 1

    return FailureHistory(
        occurrences=occurrences,
        total_observations=len(outcomes),
        consecutive_failures=consecutive_failures,
        is_first_occurrence=occurrences == 0,
    )
