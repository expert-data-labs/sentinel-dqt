"""Domain -> persistence mapping: the one-directional translation from
Milestone 0/1's immutable domain facts (Dataset, ValidationRun) into rows
ready to insert into the persistence store.

One direction only -- see docs/architecture/0003-milestone-2-architecture.md
Part 5. ``sentinel history`` reads a thin projection back
(persistence/reader.py), not a reconstructed domain object graph, so
there is no ``from_rows()`` counterpart here.

ValidationRun/Metric/QualityEvent/Incident carry no id of their own --
identity is a persistence-layer concept, assigned here as fresh UUIDs,
not a domain one. Dataset does have a stable id (a human-assigned string,
FR-01), reused as-is rather than replaced with a surrogate key.

``to_rows`` takes only a ``ValidationRun``, not a separate ``Dataset``
argument alongside it -- Milestone 0 already gave ``ValidationRun`` its
own ``dataset`` field (the full object, not a bare id) specifically so
the orchestrator's result would be self-contained. Accepting a second,
independent ``dataset`` parameter here would just be a second place the
caller could (accidentally) pass a mismatched one.

Milestone 6 adds ``IncidentRow`` and a ``details`` field on
``QualityEventRow`` -- see persistence/schema.py's own docstring for why
these are additive, not a reshape of anything that already shipped.
``run.incidents`` has one entry per non-PASS ``QualityEvent`` in
``run.quality_events`` (Milestone 5), matched by object identity rather
than position -- the same technique cli/main.py's own ``_incident_for``
already uses, since ``incidents`` is shorter than ``quality_events``
whenever some rules passed and can't be zipped positionally. Here it's
a dict keyed by ``id(event)`` built in the same loop that generates each
QualityEventRow's UUID, so the lookup is O(1) per incident rather than
cli/main.py's O(n) linear scan -- worth the dict for a mapper that runs
on every persisted run, not just once per printed summary.
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
    """One persisted Incident (Milestone 6). ``components``/``reasons``
    are JSON-encoded, the same treatment ``Metric.details`` and
    ``ThresholdResult.details`` already get -- structured context no
    dashboard view queries column-by-column, so it doesn't need
    column-by-column storage (see docs/architecture/0007-milestone-6-
    design.md Part 4). No ``created_at``: an incident's timestamp is the
    validation_runs row it belongs to, joined via ``validation_run_id``,
    exactly like QualityEvent's own timestamp already comes from its
    joined ``metrics.computed_at`` rather than a column of its own.
    """

    id: uuid.UUID
    validation_run_id: uuid.UUID
    quality_event_id: uuid.UUID
    priority: str
    score: float
    components: str
    reasons: str


@dataclass(frozen=True)
class PersistableRun:
    """Everything persist_validation_run (persistence/writer.py) needs to
    write in one transaction: the dataset row (upserted on every call --
    see writer.py's own docstring for why) plus the full row graph for
    one validation run, including its incidents (Milestone 6)."""

    dataset: DatasetRow
    run: ValidationRunRow
    metrics: tuple[MetricRow, ...]
    events: tuple[QualityEventRow, ...]
    incidents: tuple[IncidentRow, ...] = ()


def to_rows(run: ValidationRun) -> PersistableRun:
    """Translate one ValidationRun (and the Dataset and Incidents it
    already carries) into row objects ready for persistence/writer.py,
    generating fresh UUID primary keys for the run and each of its
    metrics/quality events/incidents."""
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
    # Maps id(QualityEvent) -> that event's generated QualityEventRow.id,
    # so the incidents loop below can look up each Incident's
    # quality_event_id in O(1) without re-walking quality_events.
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
