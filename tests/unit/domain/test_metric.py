from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from sentinel.domain import Metric


def test_valid_metric_constructs() -> None:
    metric = Metric(metric_name="row_count", value=1042.0, computed_at=datetime.now(UTC))
    assert metric.metric_name == "row_count"
    assert metric.value == 1042.0


def test_metric_is_frozen() -> None:
    metric = Metric(metric_name="row_count", value=1042.0, computed_at=datetime.now(UTC))
    with pytest.raises(dataclasses.FrozenInstanceError):
        metric.value = 0.0  # type: ignore[misc]


def test_details_defaults_to_none() -> None:
    """``details`` is optional."""
    metric = Metric(metric_name="row_count", value=1042.0, computed_at=datetime.now(UTC))
    assert metric.details is None


def test_details_can_carry_a_json_encoded_structured_diff() -> None:
    """``value`` is a count; ``details`` holds the breakdown as JSON."""
    payload = '{"missing_columns": ["created_at"], "unexpected_columns": [], "type_mismatches": {}}'
    metric = Metric(
        metric_name="orders_schema",
        value=1.0,
        computed_at=datetime.now(UTC),
        details=payload,
    )
    assert metric.details == payload
