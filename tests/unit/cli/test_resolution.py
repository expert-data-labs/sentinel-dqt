from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.cli.resolution import resolve_dataset, resolve_policy
from sentinel.dataset_loader import DatasetLoadError
from sentinel.domain import Criticality
from sentinel.policy_loader import PolicyLoadError

FIXTURES_DATASETS = Path(__file__).parents[2] / "fixtures" / "datasets"
FIXTURES_POLICIES = Path(__file__).parents[2] / "fixtures" / "policies"
REPO_ROOT = Path(__file__).parents[3]


def test_resolve_dataset_reads_the_env_var_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_DATASETS_DIR", str(FIXTURES_DATASETS))

    dataset = resolve_dataset("orders")

    assert dataset.id == "orders"
    assert dataset.source_type == "duckdb"
    assert dataset.criticality == Criticality.HIGH


def test_resolve_dataset_missing_name_raises_dataset_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_DATASETS_DIR", str(FIXTURES_DATASETS))

    with pytest.raises(DatasetLoadError):
        resolve_dataset("does_not_exist")


def test_resolve_policy_reads_the_env_var_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_POLICIES_DIR", str(FIXTURES_POLICIES))

    policy = resolve_policy("orders_m1")

    assert policy.dataset == "orders"
    assert len(policy.rules) == 3


def test_resolve_policy_missing_name_raises_policy_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_POLICIES_DIR", str(FIXTURES_POLICIES))

    with pytest.raises(PolicyLoadError):
        resolve_policy("does_not_exist")


def test_resolve_dataset_and_policy_default_to_the_repo_convention_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no env vars set, resolution falls back to ``datasets/`` and
    ``policies/`` relative to the current working directory — the real,
    non-test config files this milestone added at the repo root."""
    monkeypatch.delenv("SENTINEL_DATASETS_DIR", raising=False)
    monkeypatch.delenv("SENTINEL_POLICIES_DIR", raising=False)
    monkeypatch.chdir(REPO_ROOT)

    dataset = resolve_dataset("orders")
    policy = resolve_policy("orders")

    assert dataset.id == "orders"
    assert policy.dataset == "orders"
