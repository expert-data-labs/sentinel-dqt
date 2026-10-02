"""Runs a validation and records it: the one path the CLI (and later the API) uses.

Holds the dataset's run lock across the history reads and the write, so
concurrent runs of the same dataset happen one after another and each sees
the previous run's results. Different datasets run in parallel.
"""

from __future__ import annotations

import uuid

from sentinel.datasources import DataSource
from sentinel.domain import Dataset, Policy, ValidationRun
from sentinel.orchestration import ValidationOrchestrator
from sentinel.persistence.engine import StoreConnection
from sentinel.persistence.failure_history import PostgresFailureHistorySource
from sentinel.persistence.history import PostgresHistoricalMetricsSource
from sentinel.persistence.locks import dataset_run_lock
from sentinel.persistence.writer import persist_validation_run


def validate_and_record(
    conn: StoreConnection,
    dataset: Dataset,
    policy: Policy,
    source: DataSource,
    *,
    wait: bool = True,
) -> tuple[ValidationRun, uuid.UUID]:
    """Run ``policy`` against ``source`` and save the result. Returns the run and its id.

    ``wait=False`` raises DatasetRunInProgressError instead of waiting for a
    concurrent run of the same dataset.
    """
    orchestrator = ValidationOrchestrator(
        history_source=PostgresHistoricalMetricsSource(conn),
        failure_history_source=PostgresFailureHistorySource(conn),
    )
    with dataset_run_lock(conn, dataset.id, wait=wait):
        run = orchestrator.run(dataset, policy, source)
        run_id = persist_validation_run(conn, run)
    return run, run_id
