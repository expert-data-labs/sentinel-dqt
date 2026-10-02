"""The adaptive-threshold simulator (examples/simulate.py).

Runs the full pipeline (real source, real store, real history queries) over a
fixed 56-day scenario and pins the scorecard, so a change to a strategy or to
history retrieval that alters what gets caught shows up here. The scorecard
must be identical for every source: the adapters agree on the data.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from examples.simulate import (
    POLICY_PATH,
    Score,
    generate_scenario,
    render,
    score,
    simulate,
    warmup_policy,
)

from sentinel.datasources._common import MissingDriverError
from sentinel.persistence.engine import StoreConnection
from sentinel.policy_loader import load_policy

_END = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)

# (rule, strategy, caught, missed, false alarms, quiet days) over the 42 evaluated days.
_EXPECTED = [
    Score("volume_static", "static", 1, 2, 4, 35),
    Score("volume_pct_of_mean", "percentage_deviation", 2, 1, 22, 17),
    Score("volume_statistical", "statistical", 0, 3, 0, 39),
    Score("volume_median_mad", "median_mad", 2, 1, 11, 28),
    Score("volume_seasonal", "seasonal", 3, 0, 5, 34),
    Score("nulls_static", "static", 1, 0, 0, 41),
    Score("nulls_statistical", "statistical", 1, 0, 0, 41),
    Score("nulls_median_mad", "median_mad", 1, 0, 0, 41),
]


# -- the scenario (pure) ------------------------------------------------------------


def test_scenario_injects_four_labelled_anomalies_after_the_warmup() -> None:
    scenario = generate_scenario(56, 14, seed=7, end=_END)

    anomalous = [day for day in scenario if day.anomalies]
    assert len(scenario) == 56
    assert scenario[-1].at == _END
    assert [sorted(day.anomalies) for day in anomalous] == [["volume"]] * 3 + [["nulls"]]
    assert all(day.index >= 14 for day in anomalous)


def test_the_weekend_level_anomaly_lands_on_a_weekday() -> None:
    scenario = generate_scenario(56, 14, seed=7, end=_END)
    gap = next(day for day in scenario if day.note == "weekday at weekend volume")
    assert gap.at.weekday() < 5


def test_normal_days_follow_the_weekly_pattern() -> None:
    scenario = generate_scenario(56, 14, seed=7, end=_END)
    normal = [day for day in scenario if not day.anomalies]
    weekday = [d.rows for d in normal if d.at.weekday() < 5]
    weekend = [d.rows for d in normal if d.at.weekday() >= 5]
    assert min(weekday) > max(weekend)


def test_scenario_is_deterministic_for_a_seed() -> None:
    assert generate_scenario(30, 14, 3, _END) == generate_scenario(30, 14, 3, _END)


def test_too_short_a_run_is_rejected() -> None:
    with pytest.raises(ValueError, match="10 days"):
        generate_scenario(20, 14, seed=7, end=_END)


def test_warmup_policy_keeps_rule_names_with_an_always_passing_threshold() -> None:
    policy = load_policy(POLICY_PATH)
    warm = warmup_policy(policy)
    assert [r.name for r in warm.rules] == [r.name for r in policy.rules]
    assert {r.threshold.strategy for r in warm.rules} == {"static"}


# -- the full replay ------------------------------------------------------------------


@pytest.mark.parametrize("source", ["duckdb", "postgres", "mysql", "mongodb"])
def test_scorecard_is_pinned_and_identical_for_every_source(
    source: str, store: StoreConnection
) -> None:
    try:
        outcomes, policy = simulate(store, source, days=56, warmup=14, seed=7, end=_END)
    except MissingDriverError as exc:
        pytest.skip(str(exc))
    except Exception as exc:  # noqa: BLE001 - service not running locally
        if source in os.environ.get("SENTINEL_REQUIRE_BACKENDS", ""):
            raise
        pytest.skip(f"{source} unavailable: {type(exc).__name__}")

    assert len(outcomes) == 42
    assert score(outcomes, policy) == _EXPECTED
    assert "volume_seasonal" in render(outcomes, policy, source)

    runs = store.execute(
        "SELECT count(*) FROM validation_runs WHERE dataset_id = %s",
        (f"simulated_orders_{source}",),
    ).fetchone()
    assert runs == (56,)
