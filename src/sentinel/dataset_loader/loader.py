"""Reads a dataset YAML file and returns a validated Dataset (FR-01).

Mirrors sentinel.policy_loader.loader exactly, down to the reasoning: one
exception type covering every failure mode (unreadable file, invalid
YAML, schema violation), built on the shared
sentinel.config_loading.load_yaml_model rather than duplicating that
logic a second time.

This is not a dataset *registry* — there is no lookup, no versioning, no
storage beyond "a YAML file with this name exists." A real dataset
registry is a later-phase concern (see
docs/architecture/0003-milestone-2-architecture.md Part 1); this just
loads one file into one validated Dataset object, the same way
load_policy loads one policy file.
"""

from __future__ import annotations

from pathlib import Path

from sentinel.config_loading import load_yaml_model
from sentinel.domain.dataset import Dataset


class DatasetLoadError(Exception):
    """A dataset file could not be read, parsed, or validated."""


def load_dataset(path: str | Path) -> Dataset:
    return load_yaml_model(path, Dataset, DatasetLoadError)
