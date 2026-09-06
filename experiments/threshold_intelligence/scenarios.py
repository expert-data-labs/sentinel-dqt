"""Deterministic synthetic datasets for Milestone 4's threshold-strategy
comparison (docs/architecture/0005-milestone-4-design.md Part 7).

Every scenario returns a chronological ``list[ScenarioPoint]`` for a
single rule (``row_count``, standing in for any Metric a Rule produces
once per run): a real Metric plus a ground-truth ``is_anomalous`` label
that only this module knows about. That label deliberately has no home
in sentinel.domain -- a real ThresholdStrategy never receives it and
never could (there's no "ground truth" column in production); it exists
solely so this experiment can score a strategy's PASS/FAIL verdicts
against a known-correct answer.

Randomness (the small day-to-day jitter in Scenarios A/B/C) uses
``random.Random(_SEED)`` -- a fixed seed, so every run of this module
produces byte-identical output, which is what makes the results in
docs/experiments/milestone-4-results.md and the pinning tests in
tests/unit/experiments/test_runner.py reproducible rather than "usually
about right." Scenario D uses no randomness at all -- every value is the
exact figure from the milestone brief's own worked example.

Timestamps start from the first Monday on or after 2026-01-01 (computed,
not hardcoded, so this keeps working correctly regardless of what year
someone points it at) specifically so Scenario B's weekday/weekend split
lines up with real day-of-week boundaries -- SeasonalBaselineStrategy
buckets by ``Metric.computed_at.weekday()``, so the synthetic dates have
to be real, consecutive calendar days, not just "day 1, day 2, ...".
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
    """One day's Metric, plus whether it's *actually* anomalous --
    ground truth this experiment invented, never something a
    ThresholdStrategy is given or could compute itself."""

    metric: Metric
    is_anomalous: bool


def _point(value: float, computed_at: datetime, is_anomalous: bool = False) -> ScenarioPoint:
    return ScenarioPoint(
        metric=Metric(metric_name=_METRIC_NAME, value=value, computed_at=computed_at),
        is_anomalous=is_anomalous,
    )


def scenario_a_stable(n: int = 30) -> list[ScenarioPoint]:
    """Scenario A -- Stable Data: ``n`` consecutive days around 1000,
    +/- small noise, nothing anomalous. Both a static and an adaptive
    threshold are expected to pass every point (design doc Part 7)."""
    rng = random.Random(_SEED)
    return [
        _point(1000.0 + rng.uniform(-10, 10), FIRST_MONDAY + timedelta(days=i))
        for i in range(n)
    ]


def scenario_b_seasonal(weeks: int = 6) -> list[ScenarioPoint]:
    """Scenario B -- Normal Seasonal Variation, plus one genuine anomaly.

    ``weeks`` full weeks of a real weekday/weekend split (weekdays
    ~1000, weekends ~500, both +/- small noise, none of it anomalous --
    this is normal, recurring behavior, not something any strategy
    should flag). One additional point is appended on the Monday right
    after that block, at 1300 -- a genuine, one-off spike, the actual
    anomaly this scenario also needs so a strategy that flags nothing at
    all can't look "correct" by default (design doc Part 7's own
    requirement: a seasonal baseline must both accept normal seasonal
    variation *and* still catch a real anomaly).
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
    """Scenario C -- Genuine Anomaly: the same stable history as Scenario
    A (same seed, same generator -- deliberately, so any difference in a
    strategy's behavior between the two scenarios is attributable to the
    one appended point, not to different underlying noise), followed by
    one clear spike to 1800. Every strategy is expected to catch it."""
    rng = random.Random(_SEED)
    points = [
        _point(1000.0 + rng.uniform(-10, 10), FIRST_MONDAY + timedelta(days=i))
        for i in range(n_normal)
    ]
    points.append(_point(1800.0, FIRST_MONDAY + timedelta(days=n_normal), is_anomalous=True))
    return points


def scenario_d_historical_outlier() -> list[ScenarioPoint]:
    """Scenario D -- Historical Outlier: the milestone brief's own worked
    example history (1000, 1020, 980, 1010, 1005) with one extreme value
    (5000) appended twice in a row -- once as the outlier entering
    history, once as a repeat of the same-sized anomaly evaluated *after*
    the first has already contaminated the history a Mean/StdDev strategy
    would compute. That repeat is the real point of this scenario (see
    docs/experiments/milestone-4-results.md): Mean/StdDev catches the
    first occurrence (history is still clean) but misses the second (its
    own bounds have since been dragged wide by the first), while
    Median/MAD catches both.
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
    """Sanity-checks the fixtures this module's own docstring promises --
    run at import time so a change to the base date or the day arithmetic
    that silently breaks the weekday alignment fails loudly immediately,
    not three layers away inside a confusion-matrix number that just
    looks a little off."""
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
