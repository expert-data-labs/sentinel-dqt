"""Maps a ValidationRun to rows for the store (one direction only).

Runs, metrics, events and incidents get new UUIDs here; the dataset keeps its
own id. Incidents are matched to their events by object identity, since not
every event has an incident.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
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
    details: str | None = None


@dataclass(frozen=True)
class IncidentRow:
    """One stored Incident. ``components`` and ``reasons`` are JSON strings."""

    id: uuid.UUID
    validation_run_id: uuid.UUID
    quality_event_id: uuid.UUID
    priority: str
    score: float
    components: str
    reasons: str


@dataclass(frozen=True)
class PersistableRun:
    """All rows for one run, written together by persist_validation_run."""

    dataset: DatasetRow
    run: ValidationRunRow
    metrics: tuple[MetricRow, ...]
    events: tuple[QualityEventRow, ...]
    incidents: tuple[IncidentRow, ...] = ()


def to_rows(run: ValidationRun) -> PersistableRun:
    """Convert a ValidationRun into rows, generating UUIDs for each record."""
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
    # id(QualityEvent) -> its row id, for linking incidents below.
    event_row_id_by_identity: dict[int, uuid.UUID] = {}
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
        event_id = uuid.uuid4()
        event_row_id_by_identity[id(event)] = event_id
        event_rows.append(
            QualityEventRow(
                id=event_id,
                validation_run_id=run_id,
                metric_id=metric_id,
                status=event.status.value,
                expected=event.expected,
                strategy_type=event.threshold_result.strategy_type,
                severity=event.severity.value,
                blocking=event.blocking,
                details=event.threshold_details,
            )
        )

    incident_rows: list[IncidentRow] = []
    for incident in run.incidents:
        incident_rows.append(
            IncidentRow(
                id=uuid.uuid4(),
                validation_run_id=run_id,
                quality_event_id=event_row_id_by_identity[id(incident.quality_event)],
                priority=incident.priority.value,
                score=incident.score,
                components=json.dumps(asdict(incident.components)),
                reasons=json.dumps(list(incident.reasons)),
            )
        )

    return PersistableRun(
        dataset=dataset_row,
        run=run_row,
        metrics=tuple(metric_rows),
        events=tuple(event_rows),
        incidents=tuple(incident_rows),
    )
