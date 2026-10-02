from __future__ import annotations

import json

import pytest

from sentinel.domain import Status, ThresholdResult
from sentinel.prioritization.confidence import compute_confidence, extract_n_history
from sentinel.prioritization.frequency import summarize

_NO_HISTORY = summarize(())


def _result(strategy_type: str, details: dict[str, object] | None) -> ThresholdResult:
    return ThresholdResult(
        status=Status.FAIL,
        expected="n/a",
        strategy_type=strategy_type,
        details=None if details is None else json.dumps(details),
    )


def test_confidence_is_bounded_between_zero_and_one() -> None:
    result = _result("seasonal", {"n_history_in_bucket": 1000, "n_history_total": 1000})
    long_streak = summarize([Status.FAIL] * 50)
    assert 0.0 <= compute_confidence(result, long_streak) <= 1.0


def test_static_has_no_sample_size_dependence() -> None:
    """Static confidence doesn't depend on sample size (consistency still applies)."""
    small_violation = _result("static", {"actual": 5, "min": 1, "max": None})
    large_violation = _result("static", {"actual": 5000, "min": 1, "max": None})
    assert compute_confidence(small_violation, _NO_HISTORY) == compute_confidence(
        large_violation, _NO_HISTORY
    )


def test_more_historical_samples_increases_confidence_for_adaptive_strategies() -> None:
    """More history never lowers confidence."""
    thin = _result("statistical", {"n_history": 2})
    rich = _result("statistical", {"n_history": 30})
    assert compute_confidence(rich, _NO_HISTORY) >= compute_confidence(thin, _NO_HISTORY)


def test_thin_history_still_gets_a_real_but_reduced_confidence() -> None:
    """A small valid sample gives reduced, not near-zero, confidence."""
    result = _result("statistical", {"n_history": 2})
    assert compute_confidence(result, _NO_HISTORY) > 0.2


def test_missing_n_history_falls_back_to_the_floor_not_an_error() -> None:
    result = _result("statistical", {})  # no n_history key at all
    assert compute_confidence(result, _NO_HISTORY) > 0.0


def test_consecutive_failures_increase_confidence_but_are_capped() -> None:
    """More consecutive failures raise confidence, up to a cap."""
    result = _result("statistical", {"n_history": 30})
    none = compute_confidence(result, summarize([Status.PASS]))
    some = compute_confidence(result, summarize([Status.FAIL] * 3))
    a_lot = compute_confidence(result, summarize([Status.FAIL] * 100))
    assert none <= some <= a_lot
    assert a_lot <= 1.0


@pytest.mark.parametrize(
    ("weaker", "stronger"),
    [
        ("percentage_deviation", "statistical"),
        ("statistical", "median_mad"),
        ("median_mad", "seasonal"),
    ],
)
def test_strategy_robustness_ordering_from_milestone_4_results(
    weaker: str, stronger: str
) -> None:
    """Base ordering: seasonal >= median_mad >= statistical >=
    percentage_deviation.
    """
    weaker_result = _result(weaker, {"n_history": 30})
    stronger_result = _result(stronger, {"n_history": 30})
    assert compute_confidence(stronger_result, _NO_HISTORY) >= compute_confidence(
        weaker_result, _NO_HISTORY
    )


def test_extract_n_history_prefers_seasonal_bucket_size() -> None:
    result = _result("seasonal", {"n_history_in_bucket": 5, "n_history_total": 60})
    assert extract_n_history(result) == 5


def test_extract_n_history_none_when_no_details() -> None:
    result = _result("static", None)
    assert extract_n_history(result) is None
