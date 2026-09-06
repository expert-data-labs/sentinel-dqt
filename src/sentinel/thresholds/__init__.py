"""The Threshold Engine: pluggable evaluation of a Metric against expectations.

A ThresholdStrategy is the runtime-behavior half of a Threshold; the
config-time-definition half (ThresholdConfig) lives in sentinel.domain.policy.
"""

from sentinel.thresholds.base import ThresholdConfigError, ThresholdStrategy
from sentinel.thresholds.registry import (
    ThresholdStrategyNotRegisteredError,
    get_threshold_strategy,
    register_threshold_strategy,
)

__all__ = [
    "ThresholdConfigError",
    "ThresholdStrategy",
    "ThresholdStrategyNotRegisteredError",
    "get_threshold_strategy",
    "register_threshold_strategy",
]
