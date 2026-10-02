"""ThresholdStrategy interface: judge a Metric against a ThresholdConfig."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Protocol

from sentinel.domain import Metric, ThresholdConfig, ThresholdResult


class ThresholdConfigError(Exception):
    """``params`` is missing or invalid for this strategy (e.g. no min/max for static).

    Raised at evaluation time, since only the strategy knows its params.
    """


class InsufficientHistoryError(Exception):
    """Not enough history yet for an adaptive strategy's ``min_history``.

    Separate from ThresholdConfigError: the policy is fine, the dataset just
    needs more runs.
    """


class ThresholdStrategy(Protocol):
    """A registered way to decide whether a Metric is acceptable.

    ``strategy_type`` is the config's ``strategy`` value, the registry key, and
    is stamped on each ThresholdResult.
    """

    strategy_type: ClassVar[str]

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        """Judge ``metric`` against ``config``.

        ``history`` holds prior Metrics for the same rule, most recent first.
        Static ignores it; adaptive strategies raise InsufficientHistoryError when
        it's too short. Raise ThresholdConfigError for bad ``config.params``.
        """
        ...
