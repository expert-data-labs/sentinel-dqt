"""The Threshold Engine: pluggable evaluation of a Metric against expectations.

A ThresholdStrategy is the runtime-behavior half of a Threshold; the
config-time-definition half (ThresholdConfig) lives in sentinel.domain.policy.

HistoricalMetricsSource (Milestone 4) is the abstraction a ThresholdStrategy's
``history`` argument is supplied through — see sentinel.thresholds.history for
why it lives beside the strategies rather than in sentinel.persistence.
"""

from sentinel.thresholds.base import (
    InsufficientHistoryError,
    ThresholdConfigError,
    ThresholdStrategy,
)
from sentinel.thresholds.history import HistoricalMetricsSource, NullHistorySource
from sentinel.thresholds.registry import (
    ThresholdStrategyNotRegisteredError,
    get_threshold_strategy,
    register_threshold_strategy,
)

__all__ = [
    "HistoricalMetricsSource",
    "InsufficientHistoryError",
    "NullHistorySource",
    "ThresholdConfigError",
    "ThresholdStrategy",
    "ThresholdStrategyNotRegisteredError",
    "get_threshold_strategy",
    "register_threshold_strategy",
]
