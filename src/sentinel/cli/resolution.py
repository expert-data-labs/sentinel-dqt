"""Finds a dataset's YAML files by name.

Convention: ``datasets/<name>.yaml`` and ``policies/<name>.yaml``, relative to
the working directory. Override with ``SENTINEL_DATASETS_DIR`` and
``SENTINEL_POLICIES_DIR``. Loader errors propagate unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from sentinel.dataset_loader import load_dataset
from sentinel.domain import Dataset, Policy
from sentinel.policy_loader import load_policy

_DATASETS_DIR_ENV = "SENTINEL_DATASETS_DIR"
_POLICIES_DIR_ENV = "SENTINEL_POLICIES_DIR"
_DEFAULT_DATASETS_DIR = "datasets"
_DEFAULT_POLICIES_DIR = "policies"


def resolve_dataset(name: str) -> Dataset:
    """Load ``<SENTINEL_DATASETS_DIR or 'datasets'>/<name>.yaml``."""
    directory = Path(os.environ.get(_DATASETS_DIR_ENV, _DEFAULT_DATASETS_DIR))
    return load_dataset(directory / f"{name}.yaml")


def resolve_policy(name: str) -> Policy:
    """Load ``<SENTINEL_POLICIES_DIR or 'policies'>/<name>.yaml``."""
    directory = Path(os.environ.get(_POLICIES_DIR_ENV, _DEFAULT_POLICIES_DIR))
    return load_policy(directory / f"{name}.yaml")
