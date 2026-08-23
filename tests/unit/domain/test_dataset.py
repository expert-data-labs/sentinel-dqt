from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from sentinel.domain import Criticality, Dataset


def _valid_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "id": "orders",
        "name": "orders",
        "source_type": "duckdb",
        "environment": "production",
        "owner": "data-platform-team",
        "criticality": Criticality.HIGH,
    }
    kwargs.update(overrides)
    return kwargs


def test_valid_dataset_constructs() -> None:
    dataset = Dataset(**_valid_kwargs())
    assert dataset.id == "orders"
    assert dataset.criticality is Criticality.HIGH
    assert dataset.config_reference is None


def test_config_reference_is_optional_but_settable() -> None:
    dataset = Dataset(**_valid_kwargs(config_reference="policies/orders.yaml"))
    assert dataset.config_reference == "policies/orders.yaml"


@pytest.mark.parametrize(
    "missing_field",
    ["id", "name", "source_type", "environment", "owner", "criticality"],
)
def test_missing_required_field_is_rejected(missing_field: str) -> None:
    kwargs = _valid_kwargs()
    del kwargs[missing_field]
    with pytest.raises(ValidationError):
        Dataset(**kwargs)


def test_invalid_criticality_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Dataset(**_valid_kwargs(criticality="extremely-critical"))


def test_empty_string_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Dataset(**_valid_kwargs(name=""))


def test_dataset_is_frozen() -> None:
    dataset = Dataset(**_valid_kwargs())
    with pytest.raises(ValidationError):
        dataset.name = "renamed"  # type: ignore[misc]
