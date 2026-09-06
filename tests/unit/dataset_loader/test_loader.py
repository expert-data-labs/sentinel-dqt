from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.dataset_loader import DatasetLoadError, load_dataset
from sentinel.domain import Criticality

FIXTURES = Path(__file__).parents[2] / "fixtures" / "datasets"


def test_loads_a_valid_dataset() -> None:
    dataset = load_dataset(FIXTURES / "orders.yaml")

    assert dataset.id == "orders"
    assert dataset.name == "orders"
    assert dataset.source_type == "duckdb"
    assert dataset.environment == "test"
    assert dataset.owner == "data-platform-team"
    assert dataset.criticality == Criticality.HIGH
    assert dataset.config_reference == "data/orders.csv"


def test_missing_file_raises_dataset_load_error() -> None:
    with pytest.raises(DatasetLoadError):
        load_dataset(FIXTURES / "does_not_exist.yaml")


def test_invalid_yaml_syntax_raises_dataset_load_error() -> None:
    with pytest.raises(DatasetLoadError):
        load_dataset(FIXTURES / "malformed_syntax.yaml")


def test_schema_violation_raises_dataset_load_error() -> None:
    with pytest.raises(DatasetLoadError):
        load_dataset(FIXTURES / "malformed_schema.yaml")
