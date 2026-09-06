"""HistoricalMetricsSource: the abstraction that fills in ``evaluate()``'s
``history`` parameter (see ThresholdStrategy, sentinel.thresholds.base).

That parameter has existed since Milestone 0, unused until now — Milestone
4 is the first thing that needs to supply it. This module holds the
Protocol plus its trivial no-op implementation; a real, DuckDB-backed
implementation lives in ``sentinel.persistence`` (see its own module for
why), not here, because this module must not import ``duckdb`` — that's
the whole point of the abstraction (docs/architecture/0005-milestone-4-design.md
Part 2).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sentinel.domain import Metric


class HistoricalMetricsSource(Protocol):
    """Retrieves prior Metrics for one (dataset, rule) pair, so an
    adaptive ThresholdStrategy has something to compare its current
    Metric against.

    Scoped by ``dataset_id`` and ``metric_name`` — not by rule_type or
    strategy_type. ``metric_name`` is always a rule's own declared
    ``RuleConfig.name`` (see e.g. RowCountRule, NullRateRule), which is
    already the right granularity: two null_rate rules on different
    columns get different names, and therefore independent histories,
    with nothing extra needed here to keep them apart.

    A Protocol, not an ABC — the same reason DataSource and
    ThresholdStrategy are (see datasources.base, thresholds.base). A
    concrete implementation (the DuckDB-backed one in
    sentinel.persistence, a synthetic experiment's in-memory one)
    satisfies this structurally, without importing from or inheriting
    anything here. That's what lets a ThresholdStrategy depend on this
    Protocol while never depending on DuckDB, Postgres, or any other
    persistence detail.
    """

    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]:
        """Prior Metrics for ``metric_name`` against ``dataset_id``, most
        recent first.

        Order is documented as recency only — nothing beyond "earlier in
        the sequence is more recent" is guaranteed, and a caller that
        needs a specific ordering (e.g. chronological for a seasonal
        bucketing pass) sorts it itself. A source is free to cap how much
        history it returns (see the concrete DuckDB-backed source for its
        default cap); this Protocol makes no promise about totality.

        Never raises for "no history yet" — an empty sequence is the
        ordinary answer for a dataset's first run, exactly like
        ``DataSource.row_count()`` returning 0 for an empty table is
        ordinary, not exceptional. A strategy that requires a minimum
        amount of history decides that for itself (its own
        ``min_history`` param) and raises its own
        ``InsufficientHistoryError`` — this method's contract is purely
        "here is what's on record," not a judgment about whether that's
        enough to evaluate anything.
        """
        ...


class NullHistorySource:
    """A HistoricalMetricsSource that always answers "no history."

    The default for ``ValidationOrchestrator``'s ``history_source``
    parameter: every call site that predates Milestone 4 (including every
    existing test) constructs no ``history_source`` at all, gets this,
    and every strategy that predates Milestone 4 already ignores its
    ``history`` argument — so Milestone 0-3 behavior is unaffected byte
    for byte. Also useful directly in a Milestone 4 strategy's own unit
    tests when a test wants to assert "no history" without standing up
    any persistence.
    """

    def get_history(self, dataset_id: str, metric_name: str) -> Sequence[Metric]:
        return ()
