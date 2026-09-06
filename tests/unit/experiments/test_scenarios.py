"""Pins the shape of each synthetic scenario -- point counts, anomaly
counts, and determinism -- independently of any strategy. If a scenario's
generator ever changes (a different n, a different noise range, a
different seed), this is what should fail first, before any confusion-
matrix number in test_runner.py looks merely "a little off"."""

from __future__ import annotations

from experiments.threshold_intelligence.scenarios import (
    FIRST_MONDAY,
    scenario_a_stable,
    scenario_b_seasonal,
    scenario_c_genuine_anomaly,
    scenario_d_historical_outlier,
)


def test_first_monday_is_actually_a_monday() -> None:
    assert FIRST_MONDAY.weekday() == 0


def test_scenario_generators_are_deterministic() -> None:
    """Same call twice -> identical values, since each generator seeds
    its own random.Random(_SEED) rather than sharing process-global
    random state."""
    first = [p.metric.value for p in scenario_a_stable()]
    second = [p.metric.value for p in scenario_a_stable()]
    assert first == second


def test_scenario_a_has_no_anomalies() -> None:
    points = scenario_a_stable()
    assert len(points) == 30
    assert not any(p.is_anomalous for p in points)
    assert all(990.0 <= p.metric.value <= 1010.0 for p in points)


def test_scenario_b_has_exactly_one_anomaly_on_a_monday() -> None:
    points = scenario_b_seasonal()
    assert len(points) == 43  # 6 weeks x 7 days + 1 appended anomaly
    anomalies = [p for p in points if p.is_anomalous]
    assert len(anomalies) == 1
    assert anomalies[0].metric.value == 1300.0
    assert anomalies[0].metric.computed_at.weekday() == 0


def test_scenario_b_weekdays_and_weekends_are_shaped_as_documented() -> None:
    points = scenario_b_seasonal()
    normal_points = [p for p in points if not p.is_anomalous]
    weekday_values = [p.metric.value for p in normal_points if p.metric.computed_at.weekday() < 5]
    weekend_values = [p.metric.value for p in normal_points if p.metric.computed_at.weekday() >= 5]

    assert len(weekday_values) == 30  # 6 weeks x 5 weekdays
    assert len(weekend_values) == 12  # 6 weeks x 2 weekend days
    assert all(990.0 <= v <= 1010.0 for v in weekday_values)
    assert all(492.0 <= v <= 508.0 for v in weekend_values)


def test_scenario_c_has_exactly_one_anomaly_and_matches_scenario_a_otherwise() -> None:
    a_points = scenario_a_stable()
    c_points = scenario_c_genuine_anomaly()

    assert len(c_points) == len(a_points) + 1
    assert [p.metric.value for p in c_points[:30]] == [p.metric.value for p in a_points]
    assert c_points[-1].metric.value == 1800.0
    assert c_points[-1].is_anomalous is True
    assert not any(p.is_anomalous for p in c_points[:30])


def test_scenario_d_matches_the_milestone_briefs_worked_example() -> None:
    points = scenario_d_historical_outlier()
    values = [p.metric.value for p in points]

    assert values == [1000.0, 1020.0, 980.0, 1010.0, 1005.0, 5000.0, 5000.0]
    assert [p.is_anomalous for p in points] == [False, False, False, False, False, True, True]


def test_scenario_points_are_in_chronological_order() -> None:
    for scenario in (
        scenario_a_stable(),
        scenario_b_seasonal(),
        scenario_c_genuine_anomaly(),
        scenario_d_historical_outlier(),
    ):
        timestamps = [p.metric.computed_at for p in scenario]
        assert timestamps == sorted(timestamps)
