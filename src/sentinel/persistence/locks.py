"""Per-dataset run lock, so concurrent runs of one dataset happen in order.

A validation run reads the dataset's history (adaptive thresholds, failure
frequency) and then writes a new run. Two simultaneous runs of the same
dataset would otherwise read the same history and both miss each other.
Runs of different datasets don't block each other.

Uses a Postgres session-level advisory lock: it works across processes and
machines, needs no table, and is released automatically if the connection
drops. Two dataset ids with the same hash just share a lock (harmless).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sentinel.persistence.engine import StoreConnection

# First key of the two-key advisory lock, so Sentinel's locks can't collide
# with other applications using advisory locks in the same database.
_LOCK_NAMESPACE = 0x53454E54  # "SENT"


class DatasetRunInProgressError(Exception):
    """Another run of this dataset holds the lock (only raised with ``wait=False``)."""


@contextmanager
def dataset_run_lock(
    conn: StoreConnection, dataset_id: str, *, wait: bool = True
) -> Iterator[None]:
    """Hold the run lock for ``dataset_id`` for the duration of the block.

    ``wait=True`` blocks until the lock is free. ``wait=False`` raises
    DatasetRunInProgressError instead (useful for an API returning 409).
    ``conn`` can also be used for the run's own queries and write.
    """
    if wait:
        conn.execute("SELECT pg_advisory_lock(%s, hashtext(%s))", (_LOCK_NAMESPACE, dataset_id))
    else:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s, hashtext(%s))", (_LOCK_NAMESPACE, dataset_id)
        ).fetchone()
        if row is None or not row[0]:
            raise DatasetRunInProgressError(
                f"A validation run for dataset {dataset_id!r} is already in progress"
            )
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s, hashtext(%s))", (_LOCK_NAMESPACE, dataset_id))
