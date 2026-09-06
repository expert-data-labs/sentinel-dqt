"""Historical failure frequency: summarizes prior outcomes for one
(dataset, rule) pair into the smallest useful shape incident prioritization
needs -- occurrences, the window they were observed over, whether the
current failure is the first ever, and whether it's part of an ongoing
streak.

Deliberately the smallest useful abstraction (per the milestone brief's
own "do not over-engineer this"): one pure function over a plain sequence
of Status values, not a class, not a persistence-aware object. The
FailureHistorySource Protocol (sentinel.prioritization.history) fetches
raw historical outcomes; this module's only job is interpreting them --
the same division of labor sentinel.thresholds._stats already establishes
for ThresholdStrategy (a Protocol/source fetches or is handed raw facts, a
plain function turns them into a judgment).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sentinel.domain import Status


@dataclass(frozen=True)
class FailureHistory:
    """One (dataset, rule) pair's prior outcomes, summarized.

    ``occurrences`` counts WARN and FAIL alike -- both are "not a clean
    pass" from a frequency standpoint, mirroring how QualityEvent.status
    already treats WARN as worse than PASS. ``consecutive_failures`` is
    the trailing streak of non-PASS outcomes immediately preceding the
    *current* evaluation (outcomes are supplied most-recent-first, so this
    counts from the front until a PASS breaks the streak, or the sequence
    ends) -- it does not include the current occurrence itself, since that
    hasn't happened yet as far as this summary's own inputs are concerned;
    a caller explaining "this is the Nth consecutive failure" adds one for
    the occurrence being prioritized right now.

    ``frequency_rate`` is deliberately not a stored field -- it's a
    derived view (``occurrences / total_observations``) computed on
    demand, so this object only ever stores facts that can't drift out of
    sync with each other.
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
    """Turn a (dataset, rule) pair's prior outcomes -- most recent first,
    per FailureHistorySource.get_outcomes's own contract -- into a
    FailureHistory.

    An empty ``outcomes`` (a rule with no prior evaluations at all, or a
    NullFailureHistorySource) summarizes to zero occurrences and
    ``is_first_occurrence=True`` -- the smallest, least-escalated possible
    answer, matching the milestone brief's Scenario 7 requirement that a
    genuinely first-time failure not be treated as if it were recurring.
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
