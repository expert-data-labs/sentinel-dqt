"""Pins the documented outcomes of docs/experiments/milestone-4-results.md
as real assertions -- the "reproducible evidence" the milestone brief
asks for is only actually reproducible if a regression here fails a test,
not just a stale-looking number in a Markdown file nobody re-generates.

Every expected count below was derived by running this exact code (not
guessed, not hand-computed from the scenario parameters) -- see
docs/experiments/milestone-4-results.md for the narrative explanation of
*why* each number comes out the way it does. If `scenarios.py`'s seed,
noise ranges, or point counts ever change, these numbers need
regenerating (`python -m experiments.threshold_intelligence.runner`) and
these assertions need updating to match -- that divergence is the signal
this test exists to catch.
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
    """Not a bug -- see the results doc: 30 days split into 7 weekday
    buckets leaves only 4-5 points per bucket, small enough that normal
    noise occasionally reads as out-of-bounds."""
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
    """No seasonality awareness AND no tolerance for spread -- its single
    blended baseline sits between the two clusters, so both routinely
    miss its narrow band."""
    matrix = _matrix("B_seasonal", "percentage_deviation")
    assert matrix.false_positives == 26
    assert matrix.false_positives > _matrix("B_seasonal", "static").false_positives


def test_scenario_b_global_statistical_hides_the_real_anomaly() -> None:
    """The headline risk of an adaptive-but-not-seasonal baseline: zero
    false positives looks good until you notice it's because the bounds
    ballooned wide enough to also swallow the actual anomaly."""
    matrix = _matrix("B_seasonal", "statistical")
    assert matrix.false_positives == 1
    assert matrix.false_negatives == 1
    assert matrix.true_positives == 0


def test_scenario_b_global_median_mad_rejects_the_minority_cluster() -> None:
    """Robust to a rare outlier is not the same property as aware of a
    recurring pattern -- median/MAD locks onto the majority (weekday)
    cluster and rejects weekends almost as if they were outliers,
    landing close to static's own false-positive count."""
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
    """Scenario C's first 30 points are identical to Scenario A's (same
    seed, same generator) -- any strategy's false-positive count on the
    normal portion should be unchanged by the one appended anomaly."""
    for strategy in ("static", "percentage_deviation", "statistical", "median_mad", "seasonal"):
        assert (
            _matrix("C_genuine_anomaly", strategy).false_positives
            == _matrix("A_stable", strategy).false_positives
        )


# --- Scenario D: the historical-contamination effect ---


def test_scenario_d_statistical_catches_the_first_outlier_but_not_the_repeat() -> None:
    """The point of appending 5000 twice: the first occurrence is caught
    while history is still clean, but by the time the second occurs, the
    first is already inside Statistical's own history, dragging its
    bounds wide enough to miss the repeat."""
    matrix = _matrix("D_historical_outlier", "statistical")
    assert matrix.true_positives == 1
    assert matrix.false_negatives == 1


def test_scenario_d_median_mad_catches_both_occurrences() -> None:
    matrix = _matrix("D_historical_outlier", "median_mad")
    assert matrix.true_positives == 2
    assert matrix.false_negatives == 0


def test_scenario_d_seasonal_is_entirely_inapplicable() -> None:
    """7 consecutive days means every weekday occurs exactly once -- no
    bucket ever accumulates a second same-weekday point to compare
    against, so every evaluation is skipped rather than guessed."""
    matrix = _matrix("D_historical_outlier", "seasonal")
    assert matrix.skipped == 7
    assert matrix.evaluated == 0


def test_scenario_d_static_and_percentage_deviation_catch_both_regardless() -> None:
    """Not evidence of robustness -- 5000 is extreme enough that a fixed
    bound and a mean-relative percentage both reject it independent of
    the one earlier outlier (see the results doc for the caveat)."""
    for strategy in ("static", "percentage_deviation"):
        matrix = _matrix("D_historical_outlier", strategy)
        assert matrix.true_positives == 2
        assert matrix.false_negatives == 0
