"""Pure math tests for sentinel.thresholds._stats."""

from __future__ import annotations

import statistics

import pytest

from sentinel.thresholds._stats import mean_stddev_bounds, median_mad_bounds


def test_mean_stddev_bounds_centers_on_the_mean() -> None:
    values = [990.0, 1000.0, 1010.0]
    bounds = mean_stddev_bounds(values, n_sigma=3.0)

    assert bounds.center == pytest.approx(1000.0)
    assert bounds.spread == pytest.approx(statistics.stdev(values))
    assert bounds.lower == pytest.approx(bounds.center - 3.0 * bounds.spread)
    assert bounds.upper == pytest.approx(bounds.center + 3.0 * bounds.spread)


def test_mean_stddev_bounds_collapses_to_a_point_when_history_has_no_variance() -> None:
    bounds = mean_stddev_bounds([1000.0, 1000.0, 1000.0], n_sigma=3.0)

    assert bounds.center == 1000.0
    assert bounds.spread == 0.0
    assert bounds.lower == bounds.upper == 1000.0


def test_mean_stddev_bounds_requires_at_least_two_values() -> None:
    with pytest.raises(statistics.StatisticsError):
        mean_stddev_bounds([1000.0], n_sigma=3.0)


def test_median_mad_bounds_centers_on_the_median() -> None:
    values = [990.0, 1000.0, 1010.0]
    bounds = median_mad_bounds(values, n_mad=3.0)

    assert bounds.center == pytest.approx(statistics.median(values))
    assert bounds.lower == pytest.approx(bounds.center - 3.0 * bounds.spread)
    assert bounds.upper == pytest.approx(bounds.center + 3.0 * bounds.spread)


def test_median_mad_bounds_collapses_to_a_point_when_mad_is_zero() -> None:
    """Mostly identical values give MAD = 0."""
    bounds = median_mad_bounds([1000.0, 1000.0, 1000.0, 1000.0, 5000.0], n_mad=3.0)

    assert bounds.center == 1000.0
    assert bounds.spread == 0.0
    assert bounds.lower == bounds.upper == 1000.0


def test_median_mad_is_far_less_disturbed_by_a_historical_outlier_than_mean_stddev() -> None:
    """One outlier (5000) drags mean/stdev bounds; median/MAD stays near 1000."""
    history = [1000.0, 1020.0, 980.0, 1010.0, 1005.0, 5000.0]

    mean_bounds = mean_stddev_bounds(history, n_sigma=3.0)
    median_bounds = median_mad_bounds(history, n_mad=3.0)

    # The outlier drags the mean well above the cluster of real values...
    assert mean_bounds.center > 1500.0
    # ...and inflates stddev so much that the outlier itself passes.
    assert mean_bounds.lower < 1005.0 < mean_bounds.upper
    assert mean_bounds.lower < 5000.0 < mean_bounds.upper

    # Median/MAD stays anchored to the cluster the outlier doesn't belong to...
    assert median_bounds.center == pytest.approx(1007.5)
    # ...and correctly rejects the outlier as far outside its bounds.
    assert not (median_bounds.lower < 5000.0 < median_bounds.upper)
