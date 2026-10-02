"""The per-dataset run lock, using separate connections as separate processes would."""

from __future__ import annotations

import threading
import time

import pytest

from sentinel.persistence.engine import StoreConnection, connect
from sentinel.persistence.locks import DatasetRunInProgressError, dataset_run_lock


def test_a_second_run_of_the_same_dataset_is_rejected_without_waiting(
    store_url: str, store: StoreConnection
) -> None:
    with connect(store_url) as other, dataset_run_lock(store, "orders"):
        with pytest.raises(DatasetRunInProgressError, match="orders"):
            with dataset_run_lock(other, "orders", wait=False):
                pass


def test_different_datasets_do_not_block_each_other(store_url: str, store: StoreConnection) -> None:
    with connect(store_url) as other, dataset_run_lock(store, "orders"):
        with dataset_run_lock(other, "payments", wait=False):
            pass


def test_the_lock_is_released_after_the_block(store_url: str, store: StoreConnection) -> None:
    with dataset_run_lock(store, "orders"):
        pass
    with connect(store_url) as other, dataset_run_lock(other, "orders", wait=False):
        pass


def test_the_lock_is_released_when_the_block_raises(store_url: str, store: StoreConnection) -> None:
    with pytest.raises(RuntimeError), dataset_run_lock(store, "orders"):
        raise RuntimeError("run failed")
    with connect(store_url) as other, dataset_run_lock(other, "orders", wait=False):
        pass


def test_a_waiting_run_starts_only_after_the_first_finishes(
    store_url: str, store: StoreConnection
) -> None:
    events: list[str] = []

    def second_run() -> None:
        with connect(store_url) as other, dataset_run_lock(other, "orders"):
            events.append("second started")

    with dataset_run_lock(store, "orders"):
        thread = threading.Thread(target=second_run)
        thread.start()
        time.sleep(0.3)  # give the second run time to reach the lock
        events.append("first finished")
    thread.join(timeout=5)

    assert events == ["first finished", "second started"]
