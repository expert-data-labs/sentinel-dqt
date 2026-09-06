"""The ThresholdStrategy interface (FR-04): judge a Metric against a
Threshold Definition (ThresholdConfig), returning a verdict.

This is the runtime-behavior half of the Threshold definition/evaluation
pair described in the Milestone 0 architecture doc — ThresholdConfig
(sentinel.domain.policy) is the declared, config-time half.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Protocol

from sentinel.domain import Metric, ThresholdConfig, ThresholdResult


class ThresholdConfigError(Exception):
    """A ThresholdConfig's ``params`` is missing (or has an invalid) field
    its strategy_type requires — e.g. neither ``min`` nor ``max`` for the
    static strategy.

    Raised by a concrete ThresholdStrategy's ``evaluate()``, not at
    Policy-load time, for the same reason RuleConfigError isn't raised at
    load time either (see sentinel.rules.base): ThresholdConfig's
    ``params`` is deliberately an open, unvalidated dict (see
    sentinel.domain.policy) until a specific strategy is resolved and
    asked to interpret it.
    """


class InsufficientHistoryError(Exception):
    """An adaptive ThresholdStrategy was given fewer historical Metrics
    than its own ``min_history`` param requires to compute a baseline.

    Deliberately not a subclass of, or interchangeable with,
    ThresholdConfigError (Milestone 4): the two mean different things to
    whoever handles them. ThresholdConfigError says the *policy* is
    wrong — a human needs to fix a YAML file. InsufficientHistoryError
    says the policy is fine but the *data* isn't there yet — a dataset
    that's only been validated once or twice has no failure to fix,
    just history still to accumulate. Conflating them would tell a
    person "your policy is broken" when the real answer is "come back
    after a few more runs."
    """


class ThresholdStrategy(Protocol):
    """A registered, reusable way of deciding whether a Metric is
    acceptable (FR-04).

    ``strategy_type`` mirrors Rule.rule_type: it's the string a
    ThresholdConfig's ``strategy`` field names this strategy by, the key
    the registry looks it up under, and — since each implementation stamps
    its own ``strategy_type`` onto the ThresholdResult it returns — the
    record of which strategy actually ran.
    """

    strategy_type: ClassVar[str]

    def evaluate(
        self,
        metric: Metric,
        config: ThresholdConfig,
        history: Sequence[Metric] = (),
    ) -> ThresholdResult:
        """Judge ``metric`` against ``config``, returning a verdict.

        ``history`` is prior Metrics for the same rule, most recent
        first (see sentinel.thresholds.history.HistoricalMetricsSource),
        supplied by the orchestrator via an injected
        HistoricalMetricsSource — Milestone 4. A static strategy ignores
        it; an adaptive one (percentage deviation, statistical, median/
        MAD, seasonal) requires it, and raises InsufficientHistoryError
        if fewer entries are present than its own ``min_history`` param
        needs. It defaults to an empty sequence rather than being
        Optional so every implementation treats it uniformly, whether or
        not it's used.

        ``config.params`` is an unvalidated bag of whatever the policy
        author wrote (see ThresholdConfig) — interpreting it, and raising
        ThresholdConfigError if something this strategy requires is
        missing, is this method's job.
        """
        ...
