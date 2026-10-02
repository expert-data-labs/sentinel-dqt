"""Reads a dataset YAML file into a validated Dataset."""

from __future__ import annotations

from pathlib import Path

from sentinel.config_loading import load_yaml_model
from sentinel.domain.dataset import Dataset


class DatasetLoadError(Exception):
    """A dataset file could not be read, parsed, or validated."""


def load_dataset(path: str | Path) -> Dataset:
    return load_yaml_model(path, Dataset, DatasetLoadError)
