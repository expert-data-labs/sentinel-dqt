"""Resolves a dataset name (as given to ``sentinel validate <dataset>`` /
``sentinel history <dataset>``) to its Dataset and Policy configuration
on disk.

Filesystem convention, not a database-backed registry — the PRD's own
roadmap places a real dataset registry in a later phase (see
docs/architecture/0003-milestone-2-architecture.md Part 1). Two YAML
files per dataset, both named after it:
``<datasets_dir>/<name>.yaml`` (a Dataset, FR-01) and
``<policies_dir>/<name>.yaml`` (a Policy, FR-02). Directories default to
``datasets/`` and ``policies/`` relative to the current working
directory, overridable via ``SENTINEL_DATASETS_DIR`` /
``SENTINEL_POLICIES_DIR``.

A Dataset's ``config_reference`` (e.g. a CSV path for DuckDBSource) is
resolved relative to the current working directory too, not relative to
the dataset YAML file's own location — the simplest rule that works for
this milestone's single-directory local layout; revisit if datasets ever
live outside the working tree they're validated from.

Errors from the underlying loaders (DatasetLoadError, PolicyLoadError)
propagate as-is — this module doesn't wrap them further. Formatting a
resolution failure for a person to read is the CLI command's job
(sentinel.cli.main), not this module's.
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
