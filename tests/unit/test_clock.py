from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentinel import clock
from sentinel.domain import RuleConfig, ThresholdConfig
from sentinel.rules.freshness import FreshnessRule
from tests.unit.doubles import FakeDataSource

_MOMENT = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)


def test_now_is_the_real_utc_time_by_default() -> None:
    before = datetime.now(UTC)
    assert before <= clock.now() <= datetime.now(UTC)
    assert clock.now().tzinfo is not None


def test_frozen_at_pins_now_for_the_block_only() -> None:
    with clock.frozen_at(_MOMENT):
        assert clock.now() == _MOMENT
    assert clock.now() != _MOMENT


def test_frozen_at_converts_to_utc() -> None:
    ist = datetime(2026, 9, 1, 11, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    with clock.frozen_at(ist):
        assert clock.now() == _MOMENT
        assert clock.now().tzinfo is UTC


def test_frozen_at_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"), clock.frozen_at(datetime(2026, 9, 1)):
        pass


def test_pinning_in_one_thread_does_not_affect_another() -> None:
    seen: list[datetime] = []
    with clock.frozen_at(_MOMENT):
        thread = threading.Thread(target=lambda: seen.append(clock.now()))
        thread.start()
        thread.join()
    assert seen[0] != _MOMENT


def test_rules_measure_against_the_pinned_time() -> None:
    source = FakeDataSource(rows=[{"updated_at": _MOMENT - timedelta(minutes=30)}])
    config = RuleConfig(
        name="freshness",
        rule_type="freshness",
        column="updated_at",
        threshold=ThresholdConfig(strategy="static", params={"max": 60}),
    )
    with clock.frozen_at(_MOMENT):
        metric = FreshnessRule().compute(source, config)
    assert metric.value == 30.0
    assert metric.computed_at == _MOMENT
