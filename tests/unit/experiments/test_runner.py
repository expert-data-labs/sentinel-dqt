"""Pins the results in docs/experiments/threshold-strategy-evaluation.md.

Expected counts come from running the code. If scenarios change, rerun ``python
-m experiments.threshold_intelligence.runner`` and update these.
"""

from __future__ import annotations

from experiments.threshold_intelligence.runner import ConfusionMatrix, run_all

_RESULTS = run_all()


def _matrix(scenario: str, strategy: str) -> ConfusionMatrix:
    return _RESULTS[scenario][strategy]


# --- Scenario A: stable data -> zero false positives is the whole point ---


def test_scenario_a_every_strategy_has_zero_false_positives_except_seasonal() -> None:
    for strategy in ("static", "percentage_deviation", "statistical", "median_mad"):
        assert _matrix("A_stable", strategy).false_positives == 0


def test_scenario_a_seasonal_has_a_small_sample_size_false_positive() -> None:
    """Only 4-5 points per weekday bucket, so noise occasionally trips it."""
    matrix = _matrix("A_stable", "seasonal")
    assert matrix.false_positives == 1
    assert matrix.true_negatives == 15
    assert matrix.skipped == 14


def test_scenario_a_nothing_is_ever_a_false_negative() -> None:
    for strategy in _RESULTS["A_stable"]:
        assert _matrix("A_stable", strategy).false_negatives == 0


# --- Scenario B: the central demonstration ---


def test_scenario_b_static_flags_every_weekend_as_a_false_positive() -> None:
    matrix = _matrix("B_seasonal", "static")
    assert matrix.true_positives == 1  # still catches the genuine Monday spike
    assert matrix.false_positives == 12  # every one of the 12 weekend days
    assert matrix.false_negatives == 0


def test_scenario_b_percentage_deviation_is_worse_than_static() -> None:
    """One blended baseline sits between weekday and weekend values, so both miss."""
    matrix = _matrix("B_seasonal", "percentage_deviation")
    assert matrix.false_positives == 26
    assert matrix.false_positives > _matrix("B_seasonal", "static").false_positives


def test_scenario_b_global_statistical_hides_the_real_anomaly() -> None:
    """Zero false positives, but only because the band is wide enough to hide the
    spike.
    """
    matrix = _matrix("B_seasonal", "statistical")
    assert matrix.false_positives == 1
    assert matrix.false_negatives == 1
    assert matrix.true_positives == 0


def test_scenario_b_global_median_mad_rejects_the_minority_cluster() -> None:
    """Median/MAD locks onto weekdays and flags weekends, close to static."""
    matrix = _matrix("B_seasonal", "median_mad")
    assert matrix.false_positives == 12
    assert matrix.false_negatives == 0


def test_scenario_b_seasonal_is_the_only_strategy_that_gets_this_scenario_right() -> None:
    matrix = _matrix("B_seasonal", "seasonal")
    assert matrix.true_positives == 1  # catches the real anomaly
    assert matrix.false_negatives == 0
    assert matrix.false_positives == 2  # far fewer than any non-seasonal strategy
    assert matrix.false_positives < _matrix("B_seasonal", "static").false_positives
    assert matrix.false_positives < _matrix("B_seasonal", "median_mad").false_positives
    assert matrix.false_positives < _matrix("B_seasonal", "percentage_deviation").false_positives


# --- Scenario C: the easy case -- adaptive shouldn't cost detection power ---


def test_scenario_c_every_strategy_catches_the_genuine_anomaly() -> None:
    for strategy in _RESULTS["C_genuine_anomaly"]:
        matrix = _matrix("C_genuine_anomaly", strategy)
        assert matrix.true_positives == 1
        assert matrix.false_negatives == 0


def test_scenario_c_matches_scenario_a_on_false_positives() -> None:
    """C's first 30 points equal A's, so false positives should match."""
    for strategy in ("static", "percentage_deviation", "statistical", "median_mad", "seasonal"):
        assert (
            _matrix("C_genuine_anomaly", strategy).false_positives
            == _matrix("A_stable", strategy).false_positives
        )


# --- Scenario D: the historical-contamination effect ---


def test_scenario_d_statistical_catches_the_first_outlier_but_not_the_repeat() -> None:
    """The first 5000 enters history and widens the bounds, so the repeat is
    missed.
    """
    matrix = _matrix("D_historical_outlier", "statistical")
    assert matrix.true_positives == 1
    assert matrix.false_negatives == 1


def test_scenario_d_median_mad_catches_both_occurrences() -> None:
    matrix = _matrix("D_historical_outlier", "median_mad")
    assert matrix.true_positives == 2
    assert matrix.false_negatives == 0


def test_scenario_d_seasonal_is_entirely_inapplicable() -> None:
    """7 days means one point per weekday, so every evaluation is skipped."""
    matrix = _matrix("D_historical_outlier", "seasonal")
    assert matrix.skipped == 7
    assert matrix.evaluated == 0


def test_scenario_d_static_and_percentage_deviation_catch_both_regardless() -> None:
    """5000 is extreme enough that both reject it either way; not a robustness
    result.
    """
    for strategy in ("static", "percentage_deviation"):
        matrix = _matrix("D_historical_outlier", strategy)
        assert matrix.true_positives == 2
        assert matrix.false_negatives == 0
