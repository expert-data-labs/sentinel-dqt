"""Loads and validates dataset metadata from configuration files (FR-01)."""

from sentinel.dataset_loader.loader import DatasetLoadError, load_dataset

__all__ = ["DatasetLoadError", "load_dataset"]
