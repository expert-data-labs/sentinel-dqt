"""Shared, pure statistics helpers used by more than one adaptive
ThresholdStrategy (Statistical Mean/StdDev, Median/MAD, and Seasonal,
which delegates to one of the other two per bucket).

Private (leading underscore, no registry entry, not re-exported from
sentinel.thresholds) — this is an implementation detail each strategy's
own evaluate() calls into to stay as thin as StaticThresholdStrategy's is,
not a new public layer of the Threshold Engine. Nothing here knows about
Metric, ThresholdConfig, or ThresholdResult: every function takes and
returns plain floats, so it's testable — and reusable by the synthetic
experiment framework (Phase B Tasks 9-10) — without constructing any
domain object at all.

Callers are expected to have already checked their own ``min_history``
before calling into this module (see InsufficientHistoryError in
sentinel.thresholds.base) — these functions don't duplicate that check,
and will raise ``statistics.StatisticsError`` if handed too few values
(``mean_stddev_bounds`` needs at least 2; ``median_mad_bounds`` needs at
least 1, but 1 value makes every bound collapse to that value).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

# The constant that makes a (raw) Median Absolute Deviation comparable to
# a standard deviation under a normal distribution (1 / Phi^-1(3/4), the
# conventional consistency correction — see Median/MAD strategy's own
# docstring for the design doc's discussion). This is what lets
# median_mad_bounds's `n_mad` mean roughly the same thing — "how many
# standard-deviation-equivalents away" — as mean_stddev_bounds's
# `n_sigma`, rather than being an arbitrary, uncalibrated multiplier.
_MAD_TO_STDDEV_SCALE = 1.4826


@dataclass(frozen=True)
class Bounds:
    """One strategy's computed acceptable range for a Metric's value:
    where ``center`` came from (a mean or a median), how spread out the
    history was (a stddev, or a scaled MAD), and the resulting
    ``[lower, upper]`` interval a current value is checked against.

    Deliberately one generic shape across both statistical strategies,
    rather than each returning its own bespoke result — Statistical,
    Median/MAD, and Seasonal all hand this same shape to their own
    ThresholdResult.details encoding.
    """

    center: float
    spread: float
    lower: float
    upper: float


def mean_stddev_bounds(values: Sequence[float], n_sigma: float) -> Bounds:
    """``mean(values) +/- n_sigma * stdev(values)`` — the classic
    parametric bound, assuming ``values`` is approximately normally
    distributed (see the Statistical strategy's own docstring for why
    that assumption is documented rather than enforced).

    Uses the *sample* standard deviation (``statistics.stdev``, dividing
    by ``n - 1``) — the conventional choice when ``values`` is a sample
    of a dataset's history, not its entire population. This is also why
    the Statistical strategy's ``min_history`` floor is 2: ``stdev``
    itself is undefined for fewer than two values.
    """
    mean = statistics.fmean(values)
    spread = statistics.stdev(values)
    return Bounds(
        center=mean,
        spread=spread,
        lower=mean - n_sigma * spread,
        upper=mean + n_sigma * spread,
    )


def median_mad_bounds(values: Sequence[float], n_mad: float) -> Bounds:
    """``median(values) +/- n_mad * (1.4826 * MAD(values))`` — the robust
    counterpart to ``mean_stddev_bounds``.

    A single extreme historical value shifts a median by at most one
    rank position, and the MAD computed from that median by a similarly
    bounded amount — where the same extreme value can pull a mean and
    standard deviation arbitrarily far from the rest of the data (see
    docs/architecture/0005-milestone-4-design.md Part 6/Part 7, Scenario
    D, for a worked comparison against ``mean_stddev_bounds`` on an
    identical, outlier-contaminated history).
    """
    median = statistics.median(values)
    absolute_deviations = [abs(value - median) for value in values]
    mad = statistics.median(absolute_deviations)
    spread = mad * _MAD_TO_STDDEV_SCALE
    return Bounds(
        center=median,
        spread=spread,
        lower=median - n_mad * spread,
        upper=median + n_mad * spread,
    )
