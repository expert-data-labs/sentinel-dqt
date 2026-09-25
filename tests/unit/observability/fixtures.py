"""A single, deterministic, hand-built persisted history shared by every
observability test module -- one fixture, reused, rather than six
slightly-different ad hoc ones (test_queries.py, test_health.py's
integration-flavored cases, and tests/integration/
test_observability_end_to_end.py all build on this).

Deliberately constructs ValidationRun/QualityEvent/Incident objects by
hand and persists them directly via persist_validation_run, the same
style tests/unit/persistence/test_writer.py already uses -- not a real
ValidationOrchestrator.run() -- so every value here (which rule failed,
when, at what priority) is exactly what the test asserts against,
matching the milestone's own "deterministic test data" instruction.

Covers every scenario milestone 6's own test-data list asks for: a
healthy dataset (``orders``), an occasional/first-occurrence failure
(``payments`` / ``row_count``), a recurring failure (``payments`` /
``null_rate``), a persistent failure (the same pair, still failing at
``AS_OF``), a WARNING-priority incident (``customers``), a
HIGH-priority incident, a CRITICAL-priority incident, multiple
validation runs spanning more than one time window (10 days, 5 days,
2 days, 3 hours before ``AS_OF``), and enough metric history for a
trend. ``UNVALIDATED_DATASET_ID`` is registered directly with a raw SQL
insert (there is no "register a dataset with no runs yet" call in the
production write path -- persist_validation_run always upserts a
dataset alongside a run) specifically to exercise Dataset Health's
UNKNOWN case: a dataset that exists but has never been validated.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import duckdb

from sentinel.domain import (
    Criticality,
    Dataset,
    Metric,
    QualityEvent,
    Severity,
    Status,
    ThresholdResult,
    ValidationRun,
)
from sentinel.domain.incident import Incident, IncidentPriority, IncidentScoreComponents
from sentinel.persistence.writer import persist_validation_run

AS_OF = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

ORDERS_ID = "orders"
PAYMENTS_ID = "payments"
CUSTOMERS_ID = "customers"
UNVALIDATED_DATASET_ID = "unvalidated_dataset"


def _dataset(dataset_id: str, criticality: Criticality) -> Dataset:
    return Dataset(
        id=dataset_id,
        name=dataset_id,
        source_type="duckdb",
        environment="production",
        owner="data-platform-team",
        criticality=criticality,
        config_reference=f"data/{dataset_id}.csv",
    )


def _metric(name: str, value: float, computed_at: datetime) -> Metric:
    return Metric(metric_name=name, value=value, computed_at=computed_at)


def _threshold_result(
    status: Status, expected: str, actual: float, low: float | None, high: float | None
) -> ThresholdResult:
    details = json.dumps({"method": "static", "actual": actual, "min": low, "max": high})
    return ThresholdResult(
        status=status, expected=expected, strategy_type="static", details=details
    )


def _event(
    severity: Severity, metric: Metric, threshold_result: ThresholdResult
) -> QualityEvent:
    return QualityEvent(
        severity=severity, blocking=True, metric=metric, threshold_result=threshold_result
    )


def _components(base: float) -> IncidentScoreComponents:
    return IncidentScoreComponents(
        severity_score=base,
        criticality_score=base,
        deviation_score=base,
        frequency_score=base,
        confidence_score=base,
    )


def _incident(
    event: QualityEvent, priority: IncidentPriority, score: float, reasons: tuple[str, ...]
) -> Incident:
    return Incident(
        quality_event=event,
        priority=priority,
        score=score,
        components=_components(score),
        reasons=reasons,
    )


def _worst(statuses: list[Status]) -> Status:
    rank = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}
    return max(statuses, key=lambda status: rank[status]) if statuses else Status.PASS


def _run(
    dataset: Dataset,
    started_at: datetime,
    events: list[QualityEvent],
    incidents: list[Incident],
) -> ValidationRun:
    return ValidationRun(
        dataset=dataset,
        policy_version="unversioned",
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1),
        status=_worst([event.status for event in events]),
        quality_events=tuple(events),
        incidents=tuple(incidents),
    )


def seed_default_fixture(conn: duckdb.DuckDBPyConnection) -> None:
    """Persist the full deterministic history described in this module's
    docstring. Call once per test (against a fresh temp-file connection)
    before exercising ObservabilityQueryService or health.py against it."""
    orders = _dataset(ORDERS_ID, Criticality.HIGH)
    payments = _dataset(PAYMENTS_ID, Criticality.CRITICAL)
    customers = _dataset(CUSTOMERS_ID, Criticality.MEDIUM)

    # -- orders: healthy, every rule passes, every run --
    for offset in (timedelta(days=3), timedelta(hours=1)):
        started_at = AS_OF - offset
        row_count = _metric("row_count", 15_000.0, started_at)
        row_count_result = _threshold_result(Status.PASS, "row_count >= 1000", 15_000.0, 1000, None)
        event = _event(Severity.WARNING, row_count, row_count_result)
        persist_validation_run(conn, _run(orders, started_at, [event], []))

    # -- payments: null_rate recurring -> persistent; row_count first occurrence --
    # Run A: t-10d, null_rate FAILs for the first time.
    started_at = AS_OF - timedelta(days=10)
    null_rate = _metric("null_rate", 0.18, started_at)
    null_rate_result = _threshold_result(Status.FAIL, "null_rate <= 0.05", 0.18, None, 0.05)
    row_count = _metric("row_count", 9800.0, started_at + timedelta(seconds=1))
    row_count_result = _threshold_result(Status.PASS, "row_count >= 1000", 9800.0, 1000, None)
    null_rate_event = _event(Severity.HIGH, null_rate, null_rate_result)
    row_count_event = _event(Severity.WARNING, row_count, row_count_result)
    incident = _incident(
        null_rate_event,
        IncidentPriority.HIGH,
        62.0,
        ("Dataset criticality: CRITICAL", "Failure frequency: first recorded failure"),
    )
    persist_validation_run(
        conn, _run(payments, started_at, [null_rate_event, row_count_event], [incident])
    )

    # Run B: t-5d, null_rate FAILs again (now recurring).
    started_at = AS_OF - timedelta(days=5)
    null_rate = _metric("null_rate", 0.21, started_at)
    null_rate_result = _threshold_result(Status.FAIL, "null_rate <= 0.05", 0.21, None, 0.05)
    row_count = _metric("row_count", 9900.0, started_at + timedelta(seconds=1))
    row_count_result = _threshold_result(Status.PASS, "row_count >= 1000", 9900.0, 1000, None)
    null_rate_event = _event(Severity.HIGH, null_rate, null_rate_result)
    row_count_event = _event(Severity.WARNING, row_count, row_count_result)
    incident = _incident(
        null_rate_event,
        IncidentPriority.HIGH,
        68.0,
        ("Dataset criticality: CRITICAL", "Failure frequency: 1 occurrence(s)"),
    )
    persist_validation_run(
        conn, _run(payments, started_at, [null_rate_event, row_count_event], [incident])
    )

    # Run C: t-2d, null_rate still FAILing; row_count FAILs for the first time.
    started_at = AS_OF - timedelta(days=2)
    null_rate = _metric("null_rate", 0.24, started_at)
    null_rate_result = _threshold_result(Status.FAIL, "null_rate <= 0.05", 0.24, None, 0.05)
    row_count = _metric("row_count", 400.0, started_at + timedelta(seconds=1))
    row_count_result = _threshold_result(Status.FAIL, "row_count >= 1000", 400.0, 1000, None)
    null_rate_event = _event(Severity.HIGH, null_rate, null_rate_result)
    row_count_event = _event(Severity.WARNING, row_count, row_count_result)
    null_rate_incident = _incident(
        null_rate_event,
        IncidentPriority.CRITICAL,
        91.0,
        ("Dataset criticality: CRITICAL", "Failure frequency: 2 occurrence(s)"),
    )
    row_count_incident = _incident(
        row_count_event,
        IncidentPriority.WARNING,
        30.0,
        ("Dataset criticality: CRITICAL", "Failure frequency: first recorded failure"),
    )
    persist_validation_run(
        conn,
        _run(
            payments,
            started_at,
            [null_rate_event, row_count_event],
            [null_rate_incident, row_count_incident],
        ),
    )

    # Run D: t-3h (within the last 24h), null_rate still FAILing (persistent);
    # row_count back to PASS (not persistent).
    started_at = AS_OF - timedelta(hours=3)
    null_rate = _metric("null_rate", 0.30, started_at)
    null_rate_result = _threshold_result(Status.FAIL, "null_rate <= 0.05", 0.30, None, 0.05)
    row_count = _metric("row_count", 10_200.0, started_at + timedelta(seconds=1))
    row_count_result = _threshold_result(Status.PASS, "row_count >= 1000", 10_200.0, 1000, None)
    null_rate_event = _event(Severity.CRITICAL, null_rate, null_rate_result)
    row_count_event = _event(Severity.WARNING, row_count, row_count_result)
    incident = _incident(
        null_rate_event,
        IncidentPriority.CRITICAL,
        97.5,
        ("Dataset criticality: CRITICAL", "Failure frequency: 3 occurrence(s), 3 consecutive"),
    )
    persist_validation_run(
        conn, _run(payments, started_at, [null_rate_event, row_count_event], [incident])
    )

    # -- customers: one WARNING-priority incident, one run --
    started_at = AS_OF - timedelta(days=1)
    duplicate_count = _metric("duplicate_count", 42.0, started_at)
    duplicate_count_result = _threshold_result(
        Status.WARN, "duplicate_count <= 10", 42.0, None, 10
    )
    event = _event(Severity.WARNING, duplicate_count, duplicate_count_result)
    incident = _incident(
        event,
        IncidentPriority.WARNING,
        35.0,
        ("Dataset criticality: MEDIUM", "Failure frequency: first recorded failure"),
    )
    persist_validation_run(conn, _run(customers, started_at, [event], [incident]))

    # -- a dataset that has never been validated (Dataset Health: UNKNOWN) --
    # No production code path registers a dataset without a run
    # (persist_validation_run always upserts both together), so this one
    # row is inserted directly -- exactly the state a freshly-registered,
    # never-yet-run dataset would be in.
    conn.execute(
        """
        INSERT INTO datasets
            (id, name, source_type, environment, owner, criticality, config_reference)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [UNVALIDATED_DATASET_ID, UNVALIDATED_DATASET_ID, "duckdb", "production",
         "data-platform-team", Criticality.LOW.value, None],
    )
