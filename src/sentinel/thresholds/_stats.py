"""Pure statistics helpers shared by the adaptive strategies.

Works on plain floats only. Callers check ``min_history`` first; too few values
raise ``statistics.StatisticsError``.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

# Scales MAD to be comparable to a standard deviation for normal data,
# so n_mad means roughly the same as n_sigma.
_MAD_TO_STDDEV_SCALE = 1.4826


@dataclass(frozen=True)
class Bounds:
    """An acceptable range: ``center`` +/- a multiple of ``spread``."""

    center: float
    spread: float
    lower: float
    upper: float


def mean_stddev_bounds(values: Sequence[float], n_sigma: float) -> Bounds:
    """``mean +/- n_sigma * stdev`` using the sample stdev.

    Assumes roughly normal data. Needs at least 2 values.
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
    """``median +/- n_mad * (1.4826 * MAD)``.

    Robust version of mean_stddev_bounds: a single outlier barely moves the
    median or MAD.
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
