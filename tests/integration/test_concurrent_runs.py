"""Simultaneous validation runs against the shared Postgres store.

Each run uses its own connection (as separate CLI processes or API workers
would). Every orders rule fails, so each Incident's frequency reason records
how many prior observations that run saw. If runs of one dataset are properly
serialized, those counts are exactly 0, 1, 2, ... with no repeats.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from sentinel.domain import Criticality, Dataset, ValidationRun
from sentinel.persistence.engine import StoreConnection, connect
from sentinel.policy_loader import load_policy
from sentinel.registration import register_all
from sentinel.validation_service import validate_and_record
from tests.integration.test_observability_end_to_end import (
    FIXTURES_ROOT,
    _orders_data_source,
)

_RUNS_PER_DATASET = 5


def _dataset(dataset_id: str) -> Dataset:
    return Dataset(
        id=dataset_id,
        name=dataset_id,
        source_type="csv",
        environment="test",
        owner="data-platform-team",
        criticality=Criticality.HIGH,
    )


def _prior_observations(run: ValidationRun) -> int:
    """Prior observations of the row_count rule this run saw, from its incident."""
    incident = next(i for i in run.incidents if i.quality_event.rule_name == "row_count")
    reason = next(r for r in incident.reasons if r.startswith("Failure frequency"))
    match = re.search(r"in the last (\d+) observations", reason)
    return int(match.group(1)) if match else 0  # first-ever evaluation


def _run_once(store_url: str, dataset_id: str) -> ValidationRun:
    policy = load_policy(FIXTURES_ROOT / "policies" / "orders_m1.yaml")
    with connect(store_url) as conn:
        run, _ = validate_and_record(conn, _dataset(dataset_id), policy, _orders_data_source())
    return run


def test_simultaneous_runs_are_all_recorded_and_serialized_per_dataset(
    store_url: str, store: StoreConnection
) -> None:
    register_all()
    dataset_ids = ["orders_a", "orders_b"]
    jobs = [d for d in dataset_ids for _ in range(_RUNS_PER_DATASET)]

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        runs = list(pool.map(lambda d: _run_once(store_url, d), jobs))

    for dataset_id in dataset_ids:
        count = store.execute(
            "SELECT count(*) FROM validation_runs WHERE dataset_id = %s", (dataset_id,)
        ).fetchone()
        assert count == (_RUNS_PER_DATASET,)

        seen = sorted(_prior_observations(r) for r in runs if r.dataset.id == dataset_id)
        assert seen == list(range(_RUNS_PER_DATASET))
