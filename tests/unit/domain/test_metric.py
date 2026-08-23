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
