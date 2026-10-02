from __future__ import annotations

import json
from typing import Any

import pytest

from sentinel.observability.bands import expected_range


def _details(**fields: Any) -> str:
    return json.dumps(fields)


@pytest.mark.parametrize("method", ["mean_stddev", "median_mad", "seasonal_mean_stddev"])
def test_bound_based_strategies_use_their_stored_bounds(method: str) -> None:
    assert expected_range(_details(method=method, lower=90.5, upper=110)) == (90.5, 110.0)


def test_static_uses_min_and_max_either_of_which_may_be_missing() -> None:
    assert expected_range(_details(method="static", min=1000, max=None)) == (1000.0, None)
    assert expected_range(_details(method="static", min=None, max=0.01)) == (None, 0.01)


def test_percentage_deviation_is_a_band_around_the_baseline() -> None:
    lower, upper = expected_range(
        _details(method="percentage_deviation", baseline=1000, max_deviation=0.1)
    )
    assert lower == pytest.approx(900)
    assert upper == pytest.approx(1100)


def test_percentage_deviation_handles_a_negative_baseline() -> None:
    lower, upper = expected_range(
        _details(method="percentage_deviation", baseline=-200, max_deviation=0.5)
    )
    assert lower == pytest.approx(-300)
    assert upper == pytest.approx(-100)


@pytest.mark.parametrize(
    "details", [None, "", _details(method="something_new", score=3), _details(lower="n/a")]
)
def test_missing_or_unknown_details_give_no_band(details: str | None) -> None:
    assert expected_range(details) == (None, None)
