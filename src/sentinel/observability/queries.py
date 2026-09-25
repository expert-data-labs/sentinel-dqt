"""ObservabilityQueryService: the one entry point the presentation layer
(CLI or dashboard) uses to read Sentinel's persisted runtime facts back
out as presentation-shaped views.

A plain concrete class, not a Protocol with a registry -- the same
reasoning ValidationOrchestrator and IncidentPrioritizer already apply to
themselves (see their own docstrings): a Protocol/registry earns its
keep when multiple implementations are selected at runtime by a config
string. Sentinel has exactly one persistence backend for its own store
(always DuckDB, unlike the pluggable per-dataset DataSource), so there is
only ever one implementation of this class, ever -- see
docs/architecture/0007-milestone-6-design.md Part 5.

Lives in its own top-level package, not sentinel.persistence, because its
only consumer is the presentation layer -- an APPLICATION-layer concern
sitting directly on infrastructure (this milestone's own layer diagram),
the same relationship ValidationOrchestrator has to datasources/rules/
thresholds. Unlike persistence/history.py or persistence/failure_history.py
(concrete implementations of Protocols that live elsewhere specifically so
domain code never imports duckdb), nothing in the domain consumes this
class, so there is no Protocol to keep it isolated from.

Every windowed method takes an explicit ``as_of: datetime`` rather than
calling ``datetime.now(UTC)`` internally -- the presentation layer passes
real "now" at the call site, tests pass a fixed timestamp. This is what
makes every test in tests/unit/observability/ deterministic regardless of
when it happens to run.

Queries are written to avoid N+1 patterns: a bulk view across every
dataset or every (dataset, rule) pair is a bounded number of queries
(joins, GROUP BY, or one small window-function query plus one IN-list
lookup), never one query per dataset/rule/run issued in a Python loop.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum

import duckdb

from sentinel.domain import IncidentPriority, Status
from sentinel.observability.health import (
    classify_recurrence,
    derive_dataset_health,
    highest_priority,
)
from sentinel.observability.views import (
    DatasetHealthView,
    FailedRuleView,
    IncidentHistoryEntry,
    MetricTrendPoint,
    QualityHistoryEntry,
    RecurringFailureView,
)


class TimeWindow(StrEnum):
    """The three practical time ranges this milestone supports
    (docs/architecture/0007-milestone-6-design.md Part 5/11) --
    deliberately not an arbitrary date-range control."""

    LAST_24H = "24h"
    LAST_7D = "7d"
    LAST_30D = "30d"


_WINDOW_DELTAS: dict[TimeWindow, timedelta] = {
    TimeWindow.LAST_24H: timedelta(hours=24),
    TimeWindow.LAST_7D: timedelta(days=7),
    TimeWindow.LAST_30D: timedelta(days=30),
}


def _cutoff(window: TimeWindow, as_of: datetime) -> datetime:
    return as_of - _WINDOW_DELTAS[window]


def _dataset_clause(dataset_id: str | None) -> tuple[str, list[object]]:
    """An optional "AND vr.dataset_id = ?" fragment plus its bind param,
    shared by every method that accepts an optional dataset filter."""
    if dataset_id is None:
        return "", []
    return " AND vr.dataset_id = ?", [dataset_id]


def _top_reason(reasons_json: str) -> str | None:
    reasons = json.loads(reasons_json)
    return reasons[0] if reasons else None


def _build_dataset_health_view(
    dataset_id: str,
    dataset_name: str,
    latest_run: tuple[uuid.UUID, datetime, str] | None,
    failed_rules: int,
    priorities: Sequence[IncidentPriority],
) -> DatasetHealthView:
    if latest_run is None:
        return DatasetHealthView(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            health=derive_dataset_health(has_any_run=False, incident_priorities_on_latest_run=()),
            latest_validation_at=None,
            latest_run_status=None,
            highest_incident_priority=None,
            failed_rules=0,
        )
    _, started_at, status = latest_run
    highest = highest_priority(priorities)
    return DatasetHealthView(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        health=derive_dataset_health(
            has_any_run=True, incident_priorities_on_latest_run=priorities
        ),
        latest_validation_at=started_at,
        latest_run_status=status,
        highest_incident_priority=highest.value if highest is not None else None,
        failed_rules=failed_rules,
    )


class ObservabilityQueryService:
    """Reads Sentinel's persisted validation_runs/metrics/quality_events/
    incidents tables back out as the six required dashboard views.
    Stateless with respect to any single query -- ``self`` holds only the
    connection, a dependency for the instance's lifetime, the same
    pattern DuckDBHistoricalMetricsSource/DuckDBFailureHistorySource
    already use."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    # -- shared helpers, bounded-query lookups keyed by validation_run_id --

    def _priorities_for_runs(
        self, run_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[IncidentPriority]]:
        if not run_ids:
            return {}
        placeholders = ",".join("?" for _ in run_ids)
        rows = self._conn.execute(
            f"SELECT validation_run_id, priority FROM incidents "
            f"WHERE validation_run_id IN ({placeholders})",
            list(run_ids),
        ).fetchall()
        result: dict[uuid.UUID, list[IncidentPriority]] = {}
        for run_id, priority in rows:
            result.setdefault(run_id, []).append(IncidentPriority(priority))
        return result

    def _failed_counts_for_runs(self, run_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not run_ids:
            return {}
        placeholders = ",".join("?" for _ in run_ids)
        rows = self._conn.execute(
            f"SELECT validation_run_id, COUNT(*) FROM quality_events "
            f"WHERE validation_run_id IN ({placeholders}) AND status <> ? "
            f"GROUP BY validation_run_id",
            [*run_ids, Status.PASS.value],
        ).fetchall()
        return dict(rows)

    # -- Dataset Health --

    def dataset_health(self, dataset_id: str) -> DatasetHealthView:
        """A single dataset's current health -- for a dataset drill-down
        page. Use ``all_datasets_health`` for the dashboard overview
        (avoids repeating this dataset-at-a-time shape once per dataset,
        which would reintroduce the N+1 this module otherwise avoids)."""
        dataset_row = self._conn.execute(
            "SELECT id, name FROM datasets WHERE id = ?", [dataset_id]
        ).fetchone()
        if dataset_row is None:
            raise ValueError(f"No registered dataset with id {dataset_id!r}")
        _, dataset_name = dataset_row

        latest = self._conn.execute(
            """
            SELECT id, started_at, status
            FROM validation_runs
            WHERE dataset_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            [dataset_id],
        ).fetchone()

        if latest is None:
            return _build_dataset_health_view(dataset_id, dataset_name, None, 0, ())

        run_id, started_at, status = latest
        failed_rules = self._failed_counts_for_runs([run_id]).get(run_id, 0)
        priorities = self._priorities_for_runs([run_id]).get(run_id, [])
        return _build_dataset_health_view(
            dataset_id, dataset_name, (run_id, started_at, status), failed_rules, priorities
        )

    def all_datasets_health(self) -> list[DatasetHealthView]:
        """Every registered dataset's current health, for the dashboard
        overview -- four queries total (datasets, latest-run-per-dataset,
        failed counts, incident priorities), regardless of how many
        datasets or runs exist."""
        datasets = self._conn.execute("SELECT id, name FROM datasets ORDER BY name").fetchall()

        latest_rows = self._conn.execute(
            """
            SELECT dataset_id, id, started_at, status FROM (
                SELECT dataset_id, id, started_at, status,
                       ROW_NUMBER() OVER (
                           PARTITION BY dataset_id ORDER BY started_at DESC
                       ) AS rn
                FROM validation_runs
            ) ranked
            WHERE rn = 1
            """
        ).fetchall()
        latest_by_dataset: dict[str, tuple[uuid.UUID, datetime, str]] = {
            row[0]: (row[1], row[2], row[3]) for row in latest_rows
        }

        run_ids = [entry[0] for entry in latest_by_dataset.values()]
        failed_by_run = self._failed_counts_for_runs(run_ids)
        priorities_by_run = self._priorities_for_runs(run_ids)

        views: list[DatasetHealthView] = []
        for dataset_id, dataset_name in datasets:
            latest_run = latest_by_dataset.get(dataset_id)
            run_id = latest_run[0] if latest_run is not None else None
            views.append(
                _build_dataset_health_view(
                    dataset_id,
                    dataset_name,
                    latest_run,
                    failed_by_run.get(run_id, 0) if run_id is not None else 0,
                    priorities_by_run.get(run_id, []) if run_id is not None else [],
                )
            )
        return views

    # -- Quality History --

    def quality_history(
        self, dataset_id: str, window: TimeWindow, as_of: datetime
    ) -> list[QualityHistoryEntry]:
        cutoff = _cutoff(window, as_of)
        rows = self._conn.execute(
            """
            SELECT vr.id, vr.started_at, vr.status,
                   COUNT(*) AS rules_evaluated,
                   SUM(CASE WHEN qe.status <> ? THEN 1 ELSE 0 END) AS rules_failed
            FROM validation_runs vr
            JOIN quality_events qe ON qe.validation_run_id = vr.id
            WHERE vr.dataset_id = ? AND vr.started_at >= ?
            GROUP BY vr.id, vr.started_at, vr.status
            ORDER BY vr.started_at DESC
            """,
            [Status.PASS.value, dataset_id, cutoff],
        ).fetchall()

        run_ids = [row[0] for row in rows]
        priorities_by_run = self._priorities_for_runs(run_ids)

        return [
            QualityHistoryEntry(
                run_id=run_id,
                started_at=started_at,
                rules_evaluated=rules_evaluated,
                rules_failed=rules_failed,
                overall_status=status,
                highest_incident_priority=(
                    priority.value
                    if (priority := highest_priority(priorities_by_run.get(run_id, [])))
                    is not None
                    else None
                ),
            )
            for run_id, started_at, status, rules_evaluated, rules_failed in rows
        ]

    def rule_names_for_dataset(self, dataset_id: str) -> list[str]:
        """Every rule name (metric_name) ever evaluated for this dataset,
        sorted -- glue for a presentation-layer metric selector (e.g. the
        dashboard's per-dataset Metric Trends dropdown), not one of the
        six required views itself."""
        rows = self._conn.execute(
            """
            SELECT DISTINCT m.metric_name
            FROM metrics m
            JOIN validation_runs vr ON vr.id = m.validation_run_id
            WHERE vr.dataset_id = ?
            ORDER BY m.metric_name
            """,
            [dataset_id],
        ).fetchall()
        return [row[0] for row in rows]

    # -- Metric Trends --

    def metric_trend(
        self, dataset_id: str, metric_name: str, window: TimeWindow, as_of: datetime
    ) -> list[MetricTrendPoint]:
        cutoff = _cutoff(window, as_of)
        rows = self._conn.execute(
            """
            SELECT m.value, m.computed_at, qe.details
            FROM metrics m
            JOIN validation_runs vr ON vr.id = m.validation_run_id
            LEFT JOIN quality_events qe ON qe.metric_id = m.id
            WHERE vr.dataset_id = ? AND m.metric_name = ? AND m.computed_at >= ?
            ORDER BY m.computed_at ASC
            """,
            [dataset_id, metric_name, cutoff],
        ).fetchall()
        return [
            MetricTrendPoint(computed_at=computed_at, value=value, threshold_details=details)
            for value, computed_at, details in rows
        ]

    # -- Failed Rules --

    def failed_rules(
        self, window: TimeWindow, as_of: datetime, dataset_id: str | None = None
    ) -> list[FailedRuleView]:
        cutoff = _cutoff(window, as_of)
        clause, clause_params = _dataset_clause(dataset_id)

        counts = self._conn.execute(
            f"""
            SELECT vr.dataset_id, m.metric_name, COUNT(*) AS failure_count,
                   MAX(m.computed_at) AS latest_failure_at
            FROM quality_events qe
            JOIN metrics m ON m.id = qe.metric_id
            JOIN validation_runs vr ON vr.id = qe.validation_run_id
            WHERE qe.status <> ? AND m.computed_at >= ?{clause}
            GROUP BY vr.dataset_id, m.metric_name
            ORDER BY failure_count DESC
            """,
            [Status.PASS.value, cutoff, *clause_params],
        ).fetchall()

        latest_priority_rows = self._conn.execute(
            f"""
            SELECT dataset_id, metric_name, priority FROM (
                SELECT vr.dataset_id AS dataset_id, m.metric_name AS metric_name,
                       i.priority AS priority,
                       ROW_NUMBER() OVER (
                           PARTITION BY vr.dataset_id, m.metric_name
                           ORDER BY m.computed_at DESC
                       ) AS rn
                FROM quality_events qe
                JOIN metrics m ON m.id = qe.metric_id
                JOIN validation_runs vr ON vr.id = qe.validation_run_id
                JOIN incidents i ON i.quality_event_id = qe.id
                WHERE qe.status <> ? AND m.computed_at >= ?{clause}
            ) ranked
            WHERE rn = 1
            """,
            [Status.PASS.value, cutoff, *clause_params],
        ).fetchall()
        current_priority = {
            (row[0], row[1]): row[2] for row in latest_priority_rows
        }

        return [
            FailedRuleView(
                dataset_id=ds_id,
                rule_name=rule_name,
                failure_count=failure_count,
                latest_failure_at=latest_failure_at,
                current_priority=current_priority.get((ds_id, rule_name)),
            )
            for ds_id, rule_name, failure_count, latest_failure_at in counts
        ]

    # -- Incident History --

    def incident_history(
        self,
        window: TimeWindow,
        as_of: datetime,
        dataset_id: str | None = None,
        priority: IncidentPriority | None = None,
        rule_name: str | None = None,
    ) -> list[IncidentHistoryEntry]:
        cutoff = _cutoff(window, as_of)
        clauses = ["m.computed_at >= ?"]
        params: list[object] = [cutoff]
        if dataset_id is not None:
            clauses.append("vr.dataset_id = ?")
            params.append(dataset_id)
        if priority is not None:
            clauses.append("i.priority = ?")
            params.append(priority.value)
        if rule_name is not None:
            clauses.append("m.metric_name = ?")
            params.append(rule_name)
        where = " AND ".join(clauses)

        rows = self._conn.execute(
            f"""
            SELECT i.id, m.computed_at, vr.dataset_id, m.metric_name, i.priority, i.score,
                   i.reasons
            FROM incidents i
            JOIN quality_events qe ON qe.id = i.quality_event_id
            JOIN metrics m ON m.id = qe.metric_id
            JOIN validation_runs vr ON vr.id = i.validation_run_id
            WHERE {where}
            ORDER BY m.computed_at DESC
            """,
            params,
        ).fetchall()

        return [
            IncidentHistoryEntry(
                incident_id=incident_id,
                occurred_at=occurred_at,
                dataset_id=ds_id,
                rule_name=rule_name_,
                priority=priority_,
                score=score,
                top_reason=_top_reason(reasons),
            )
            for incident_id, occurred_at, ds_id, rule_name_, priority_, score, reasons in rows
        ]

    # -- Recurring Failures --

    def recurring_failures(
        self, window: TimeWindow, as_of: datetime, dataset_id: str | None = None
    ) -> list[RecurringFailureView]:
        cutoff = _cutoff(window, as_of)
        clause, clause_params = _dataset_clause(dataset_id)

        counts = self._conn.execute(
            f"""
            SELECT vr.dataset_id, m.metric_name, COUNT(*) AS failure_count,
                   MAX(m.computed_at) AS last_seen_at
            FROM quality_events qe
            JOIN metrics m ON m.id = qe.metric_id
            JOIN validation_runs vr ON vr.id = qe.validation_run_id
            WHERE qe.status <> ? AND m.computed_at >= ?{clause}
            GROUP BY vr.dataset_id, m.metric_name
            """,
            [Status.PASS.value, cutoff, *clause_params],
        ).fetchall()

        # "Is this pair still broken right now" is a question about the
        # single most recent evaluation of that rule ever -- deliberately
        # NOT time-windowed (see health.classify_recurrence's own
        # docstring), so this query has no ``cutoff`` filter.
        latest_status_rows = self._conn.execute(
            f"""
            SELECT dataset_id, metric_name, status FROM (
                SELECT vr.dataset_id AS dataset_id, m.metric_name AS metric_name,
                       qe.status AS status,
                       ROW_NUMBER() OVER (
                           PARTITION BY vr.dataset_id, m.metric_name
                           ORDER BY m.computed_at DESC
                       ) AS rn
                FROM quality_events qe
                JOIN metrics m ON m.id = qe.metric_id
                JOIN validation_runs vr ON vr.id = qe.validation_run_id
                WHERE 1 = 1{clause}
            ) ranked
            WHERE rn = 1
            """,
            clause_params,
        ).fetchall()
        latest_status = {(row[0], row[1]): row[2] for row in latest_status_rows}

        views: list[RecurringFailureView] = []
        for ds_id, rule_name, failure_count, last_seen_at in counts:
            most_recent_failed = latest_status.get((ds_id, rule_name)) != Status.PASS.value
            views.append(
                RecurringFailureView(
                    dataset_id=ds_id,
                    rule_name=rule_name,
                    failure_count=failure_count,
                    last_seen_at=last_seen_at,
                    classification=classify_recurrence(failure_count, most_recent_failed),
                )
            )
        return views
