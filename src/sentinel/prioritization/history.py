"""FailureHistorySource: the abstraction that answers "how has this rule
behaved historically" for incident prioritization (Milestone 5).

This is a deliberately separate abstraction from
sentinel.thresholds.history.HistoricalMetricsSource, not a reuse of it.
HistoricalMetricsSource answers "what were the historical *values*" -- it
returns bare Metrics, with no pass/fail outcome attached, which is exactly
enough for an adaptive ThresholdStrategy to compute a baseline. Incident
prioritization needs a different question answered -- "how often has this
rule *failed*" -- which requires the Status each historical evaluation
actually produced, information HistoricalMetricsSource's contract never
carries. See docs/architecture/0006-milestone-5-design.md Part 5.

Lives beside sentinel.thresholds.history in spirit (a Protocol, no duckdb
import) for the identical reason: a concrete, DuckDB-backed implementation
lives in sentinel.persistence (see persistence/failure_history.py), so
this module -- and anything that depends only on this Protocol, like
sentinel.prioritization.frequency and IncidentPrioritizer -- never needs to
import duckdb.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sentinel.domain import Status


class FailureHistorySource(Protocol):
    """Retrieves prior QualityEvent outcomes for one (dataset, rule) pair,
    so historical failure frequency (sentinel.prioritization.frequency) has
    something to summarize.

    Scoped by ``dataset_id`` and ``metric_name``, the same granularity
    HistoricalMetricsSource already uses (see its own docstring for why
    that's the right level: a rule's own declared ``RuleConfig.name``
    already keeps e.g. two null_rate rules on different columns
    independent).
    """

    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        """Prior evaluation outcomes for ``metric_name`` against
        ``dataset_id``, most recent first.

        Order is recency only, mirroring HistoricalMetricsSource.get_history's
        own contract -- and, like that method, this one is free to cap how
        much history it returns (see the concrete DuckDB-backed source for
        its default cap) and makes no promise of totality. A row-count cap
        rather than a wall-clock window is a deliberate simplicity choice:
        it keeps this deterministic and trivially testable, at the
        documented cost that a dataset validated more often will appear to
        accumulate "frequent failure" status faster than one validated
        less often for the same underlying failure rate (see the design
        doc's Part 5 trade-off note).

        Never raises for "no history yet" -- an empty sequence is the
        ordinary answer for a rule's first-ever evaluation, exactly like
        HistoricalMetricsSource.get_history's own "no history" contract.
        """
        ...


class NullFailureHistorySource:
    """A FailureHistorySource that always answers "no history."

    The default for anything that accepts a FailureHistorySource (see
    IncidentPrioritizer and ValidationOrchestrator) -- every call site that
    predates Milestone 5, and every test that doesn't care about frequency
    scoring specifically, gets this and sees every rule treated as a first
    occurrence (sentinel.prioritization.frequency.summarize's own contract
    for an empty outcome sequence).
    """

    def get_outcomes(self, dataset_id: str, metric_name: str) -> Sequence[Status]:
        return ()
