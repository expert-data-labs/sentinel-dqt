"""Deterministic synthetic scenarios for comparing threshold strategies.

Each scenario is a chronological list of daily row_count Metrics, each labeled
with whether it is truly anomalous (ground truth used only for scoring). Noise
uses a fixed seed, so results are reproducible. Dates start on a Monday so
weekday patterns line up for the seasonal strategy.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sentinel.domain import Metric

_SEED = 42
_METRIC_NAME = "row_count"

_YEAR_START = datetime(2026, 1, 1, tzinfo=UTC)
FIRST_MONDAY = _YEAR_START + timedelta(days=(7 - _YEAR_START.weekday()) % 7)


@dataclass(frozen=True)
class ScenarioPoint:
    """One day's Metric plus its ground-truth anomaly label."""

    metric: Metric
    is_anomalous: bool


def _point(value: float, computed_at: datetime, is_anomalous: bool = False) -> ScenarioPoint:
    return ScenarioPoint(
        metric=Metric(metric_name=_METRIC_NAME, value=value, computed_at=computed_at),
        is_anomalous=is_anomalous,
    )


def scenario_a_stable(n: int = 30) -> list[ScenarioPoint]:
    """A - stable: ``n`` days around 1000 with small noise. No anomalies."""
    rng = random.Random(_SEED)
    return [
        _point(1000.0 + rng.uniform(-10, 10), FIRST_MONDAY + timedelta(days=i))
        for i in range(n)
    ]


def scenario_b_seasonal(weeks: int = 6) -> list[ScenarioPoint]:
    """B - seasonal: weekdays ~1000, weekends ~500, then one real spike (1300).

    Tests that a strategy ignores the weekly pattern but still catches the
    spike.
    """
    rng = random.Random(_SEED)
    points: list[ScenarioPoint] = []
    for day in range(weeks * 7):
        computed_at = FIRST_MONDAY + timedelta(days=day)
        if computed_at.weekday() < 5:  # Monday-Friday
            value = 1000.0 + rng.uniform(-10, 10)
        else:  # Saturday-Sunday
            value = 500.0 + rng.uniform(-8, 8)
        points.append(_point(value, computed_at))

    anomaly_day = FIRST_MONDAY + timedelta(days=weeks * 7)
    points.append(_point(1300.0, anomaly_day, is_anomalous=True))
    return points


def scenario_c_genuine_anomaly(n_normal: int = 30) -> list[ScenarioPoint]:
    """C - genuine anomaly: Scenario A's data followed by one spike to 1800."""
    rng = random.Random(_SEED)
    points = [
        _point(1000.0 + rng.uniform(-10, 10), FIRST_MONDAY + timedelta(days=i))
        for i in range(n_normal)
    ]
    points.append(_point(1800.0, FIRST_MONDAY + timedelta(days=n_normal), is_anomalous=True))
    return points


def scenario_d_historical_outlier() -> list[ScenarioPoint]:
    """D - historical outlier: a short stable history, then 5000 twice.

    Mean/stdev catches the first 5000 but misses the second (the first widened
    its bounds). Median/MAD catches both.
    """
    normal_values = (1000.0, 1020.0, 980.0, 1010.0, 1005.0)
    points = [
        _point(value, FIRST_MONDAY + timedelta(days=i))
        for i, value in enumerate(normal_values)
    ]
    points.append(
        _point(5000.0, FIRST_MONDAY + timedelta(days=len(normal_values)), is_anomalous=True)
    )
    points.append(
        _point(5000.0, FIRST_MONDAY + timedelta(days=len(normal_values) + 1), is_anomalous=True)
    )
    return points


ALL_SCENARIOS: dict[str, list[ScenarioPoint]] = {
    "A_stable": scenario_a_stable(),
    "B_seasonal": scenario_b_seasonal(),
    "C_genuine_anomaly": scenario_c_genuine_anomaly(),
    "D_historical_outlier": scenario_d_historical_outlier(),
}


def _self_check() -> None:
    """Check at import time that dates and weekday alignment are correct."""
    assert FIRST_MONDAY.weekday() == 0, "FIRST_MONDAY must actually be a Monday"
    b = ALL_SCENARIOS["B_seasonal"]
    weekday_count = sum(1 for p in b if p.metric.computed_at.weekday() < 5)
    weekend_count = sum(1 for p in b if p.metric.computed_at.weekday() >= 5)
    assert weekday_count == 5 * 6 + 1  # 6 weeks of weekdays + the appended Monday anomaly
    assert weekend_count == 2 * 6
    assert sum(1 for p in b if p.is_anomalous) == 1


_self_check()


if __name__ == "__main__":
    for name, points in ALL_SCENARIOS.items():
        values = [p.metric.value for p in points]
        print(
            f"{name}: n={len(points)}, anomalies={sum(p.is_anomalous for p in points)}, "
            f"min={min(values):.1f}, max={max(values):.1f}, mean={statistics.fmean(values):.1f}"
        )
