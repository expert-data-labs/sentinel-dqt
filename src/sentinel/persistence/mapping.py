"""Domain -> persistence mapping: the one-directional translation from
Milestone 0/1's immutable domain facts (Dataset, ValidationRun) into rows
ready to insert into the persistence store.

One direction only — see docs/architecture/0003-milestone-2-architecture.md
Part 5. ``sentinel history`` reads a thin projection back
(persistence/reader.py), not a reconstructed domain object graph, so
there is no ``from_rows()`` counterpart here.

ValidationRun/Metric/QualityEvent carry no id of their own — identity is
a persistence-layer concept, assigned here as fresh UUIDs, not a domain
one. Dataset does have a stable id (a human-assigned string, FR-01),
reused as-is rather than replaced with a surrogate key.

``to_rows`` takes only a ``ValidationRun``, not a separate ``Dataset``
argument alongside it — Milestone 0 already gave ``ValidationRun`` its
own ``dataset`` field (the full object, not a bare id) specifically so
the orchestrator's result would be self-contained. Accepting a second,
independent ``dataset`` parameter here would just be a second place the
caller could (accidentally) pass a mismatched one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sentinel.domain import ValidationRun


@dataclass(frozen=True)
class DatasetRow:
    id: str
    name: str
    source_type: str
    environment: str
    owner: str
    criticality: str
    config_reference: str | None


@dataclass(frozen=True)
class ValidationRunRow:
    id: uuid.UUID
    dataset_id: str
    policy_version: str
    started_at: datetime
    finished_at: datetime
    status: str


@dataclass(frozen=True)
class MetricRow:
    id: uuid.UUID
    validation_run_id: uuid.UUID
    metric_name: str
    value: float
    computed_at: datetime


@dataclass(frozen=True)
class QualityEventRow:
    id: uuid.UUID
    validation_run_id: uuid.UUID
    metric_id: uuid.UUID
    status: str
    expected: str
    strategy_type: str
    severity: str
    blocking: bool


@dataclass(frozen=True)
class PersistableRun:
    """Everything persist_validation_run (persistence/writer.py) needs to
    write in one transaction: the dataset row (upserted on every call —
    see writer.py's own docstring for why) plus the full row graph for
    one validation run."""

    dataset: DatasetRow
    run: ValidationRunRow
    metrics: tuple[MetricRow, ...]
    events: tuple[QualityEventRow, ...]


def to_rows(run: ValidationRun) -> PersistableRun:
    """Translate one ValidationRun (and the Dataset it already carries)
    into row objects ready for persistence/writer.py, generating fresh
    UUID primary keys for the run and each of its metrics/quality
    events."""
    dataset = run.dataset
    dataset_row = DatasetRow(
        id=dataset.id,
        name=dataset.name,
        source_type=dataset.source_type,
        environment=dataset.environment,
        owner=dataset.owner,
        criticality=dataset.criticality.value,
        config_reference=dataset.config_reference,
    )

    run_id = uuid.uuid4()
    run_row = ValidationRunRow(
        id=run_id,
        dataset_id=dataset.id,
        policy_version=run.policy_version,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status.value,
    )

    metric_rows: list[MetricRow] = []
    event_rows: list[QualityEventRow] = []
    for event in run.quality_events:
        metric_id = uuid.uuid4()
        metric_rows.append(
            MetricRow(
                id=metric_id,
                validation_run_id=run_id,
                metric_name=event.metric.metric_name,
                value=event.metric.value,
                computed_at=event.metric.computed_at,
            )
        )
        event_rows.append(
            QualityEventRow(
                id=uuid.uuid4(),
                validation_run_id=run_id,
                metric_id=metric_id,
                status=event.status.value,
                expected=event.expected,
                strategy_type=event.threshold_result.strategy_type,
                severity=event.severity.value,
                blocking=event.blocking,
            )
        )

    return PersistableRun(
        dataset=dataset_row,
        run=run_row,
        metrics=tuple(metric_rows),
        events=tuple(event_rows),
    )
