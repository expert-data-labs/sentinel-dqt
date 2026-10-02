from __future__ import annotations

import json

import pytest

from sentinel.domain import Status, ThresholdResult
from sentinel.prioritization.deviation import compute_deviation_ratio


def _result(strategy_type: str, details: dict[str, object] | None) -> ThresholdResult:
    return ThresholdResult(
        status=Status.FAIL,
        expected="n/a",
        strategy_type=strategy_type,
        details=None if details is None else json.dumps(details),
    )


def test_no_details_returns_none() -> None:
    assert compute_deviation_ratio(_result("static", None)) is None


def test_unrecognized_strategy_type_returns_none() -> None:
    result = _result("some_future_strategy", {"actual": 1, "lower": 0, "upper": 2})
    assert compute_deviation_ratio(result) is None


# -- percentage_deviation --------------------------------------------------


def test_percentage_deviation_ratio_is_deviation_over_max_deviation() -> None:
    result = _result(
        "percentage_deviation",
        {"deviation": 0.05, "max_deviation": 0.10, "actual": 1050, "baseline": 1000},
    )
    assert compute_deviation_ratio(result) == pytest.approx(0.5)


def test_percentage_deviation_negative_deviation_uses_absolute_value() -> None:
    result = _result(
        "percentage_deviation",
        {"deviation": -0.20, "max_deviation": 0.10},
    )
    assert compute_deviation_ratio(result) == pytest.approx(2.0)


def test_percentage_deviation_undefined_baseline_saturates() -> None:
    """Zero baseline with a non-zero value gives the maximum ratio."""
    result = _result("percentage_deviation", {"deviation": None, "max_deviation": 0.10})
    assert compute_deviation_ratio(result) == 2.0


# -- static -----------------------------------------------------------------


def test_static_ratio_below_min_bound() -> None:
    result = _result("static", {"actual": 500, "min": 1000, "max": None})
    assert compute_deviation_ratio(result) == pytest.approx(0.5)


def test_static_ratio_above_max_bound() -> None:
    result = _result("static", {"actual": 150, "min": None, "max": 100})
    assert compute_deviation_ratio(result) == pytest.approx(0.5)


def test_static_ratio_within_bounds_is_zero() -> None:
    result = _result("static", {"actual": 50, "min": 10, "max": 100})
    assert compute_deviation_ratio(result) == 0.0


def test_static_ratio_zero_bound_saturates() -> None:
    """A breached bound of 0 gives the maximum ratio instead of dividing by zero."""
    result = _result("static", {"actual": 5, "min": None, "max": 0})
    assert compute_deviation_ratio(result) == 2.0


def test_static_ratio_negative_values() -> None:
    """Negative bounds still give a sensible ratio."""
    result = _result("static", {"actual": -150, "min": -100, "max": None})
    assert compute_deviation_ratio(result) == pytest.approx(0.5)


# -- bound-based (statistical / median_mad / seasonal) -----------------------


@pytest.mark.parametrize("strategy_type", ["statistical", "median_mad", "seasonal"])
def test_bound_based_ratio_at_the_edge_is_one(strategy_type: str) -> None:
    result = _result(strategy_type, {"actual": 110, "lower": 90, "upper": 110})
    assert compute_deviation_ratio(result) == pytest.approx(1.0)


@pytest.mark.parametrize("strategy_type", ["statistical", "median_mad", "seasonal"])
def test_bound_based_ratio_at_center_is_zero(strategy_type: str) -> None:
    result = _result(strategy_type, {"actual": 100, "lower": 90, "upper": 110})
    assert compute_deviation_ratio(result) == pytest.approx(0.0)


def test_bound_based_ratio_beyond_the_edge_exceeds_one() -> None:
    result = _result("statistical", {"actual": 130, "lower": 90, "upper": 110})
    assert compute_deviation_ratio(result) == pytest.approx(3.0)


def test_bound_based_ratio_does_not_need_the_strategy_specific_center_key() -> None:
    """Center is the midpoint of lower/upper (100); 110 is halfway to 120, so 0.5."""
    result = _result("median_mad", {"actual": 110, "lower": 80, "upper": 120})
    assert compute_deviation_ratio(result) == pytest.approx(0.5)


def test_bound_based_zero_width_bounds_saturates() -> None:
    result = _result("seasonal", {"actual": 5, "lower": 5, "upper": 5})
    assert compute_deviation_ratio(result) == 2.0


def test_bound_based_missing_key_returns_none() -> None:
    result = _result("statistical", {"actual": 100, "lower": 90})  # no "upper"
    assert compute_deviation_ratio(result) is None
