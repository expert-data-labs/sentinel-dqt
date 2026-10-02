"""Threshold engine: pluggable strategies that judge a Metric.

ThresholdConfig (in sentinel.domain.policy) is the config; a ThresholdStrategy
is the behavior. HistoricalMetricsSource supplies past metrics to adaptive
strategies.
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
