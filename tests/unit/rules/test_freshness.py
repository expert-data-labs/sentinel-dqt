from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sentinel.domain import RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.freshness import FreshnessRule
from tests.unit.doubles import FakeDataSource


def _rule_config(column: str | None = "updated_at") -> RuleConfig:
    data: dict[str, object] = {
        "name": "orders_freshness",
        "type": "freshness",
        "threshold": {"strategy": "static", "max": 60},
    }
    if column is not None:
        data["column"] = column
    return RuleConfig.model_validate(data)


def test_freshness_minutes_measures_elapsed_time_since_the_latest_timestamp() -> None:
    latest = datetime.now(UTC) - timedelta(minutes=10)
    source = FakeDataSource(rows=[{"updated_at": latest}])
    metric = FreshnessRule().compute(source, _rule_config())
    # small slack for wall-clock time between fixture creation and compute()
    assert metric.value == pytest.approx(10.0, abs=0.5)


def test_a_stale_dataset_still_just_reports_its_age_no_pass_fail_here() -> None:
    """FreshnessRule never decides stale vs. fresh -- see the rule's own
    docstring and sentinel.rules.base. A large freshness_minutes value is
    exactly as valid an output as a small one; StaticThresholdStrategy is
    what turns it into a verdict, unchanged from every other rule."""
    latest = datetime.now(UTC) - timedelta(days=2)
    source = FakeDataSource(rows=[{"updated_at": latest}])
    metric = FreshnessRule().compute(source, _rule_config())
    assert metric.value == pytest.approx(2 * 24 * 60, abs=1.0)


def test_empty_dataset_is_infinitely_stale_not_a_crash() -> None:
    source = FakeDataSource(rows=[])
    metric = FreshnessRule().compute(source, _rule_config())
    assert metric.value == float("inf")


def test_all_null_timestamp_column_is_infinitely_stale() -> None:
    source = FakeDataSource(rows=[{"updated_at": None}, {"updated_at": None}])
    metric = FreshnessRule().compute(source, _rule_config())
    assert metric.value == float("inf")


def test_some_null_timestamps_are_ignored_same_as_max_value_does() -> None:
    latest = datetime.now(UTC) - timedelta(minutes=5)
    source = FakeDataSource(
        rows=[{"updated_at": latest}, {"updated_at": None}, {"updated_at": None}]
    )
    metric = FreshnessRule().compute(source, _rule_config())
    assert metric.value == pytest.approx(5.0, abs=0.5)


def test_a_future_timestamp_reports_as_negative_minutes_not_clamped_to_zero() -> None:
    future = datetime.now(UTC) + timedelta(minutes=30)
    source = FakeDataSource(rows=[{"updated_at": future}])
    metric = FreshnessRule().compute(source, _rule_config())
    assert metric.value < 0
    assert metric.value == pytest.approx(-30.0, abs=0.5)


def test_missing_column_raises_rule_config_error() -> None:
    source = FakeDataSource(rows=[{"updated_at": datetime.now(UTC)}])
    with pytest.raises(RuleConfigError, match="column"):
        FreshnessRule().compute(source, _rule_config(column=None))
