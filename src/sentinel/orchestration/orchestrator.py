"""ValidationOrchestrator: runs a Policy's rules against a Dataset's
DataSource and assembles the outcome as a ValidationRun.

This is Milestone 0's skeleton — it proves Rule, ThresholdStrategy, and
DataSource wire together correctly through their registries, using the
fake/dummy implementations built for Tasks 4-6. No real Rule or
ThresholdStrategy exists yet; those are Milestone 1's job (the four rules
in the PRD's example policy) and beyond.

A deliberate deviation from the Milestone 0 architecture doc's sketch:
that doc listed ValidationOrchestrator as a fourth Protocol alongside Rule,
ThresholdStrategy, and DataSource. Building it revealed that reasoning
doesn't actually hold — Rule/ThresholdStrategy/DataSource are Protocols
because multiple concrete implementations are selected at runtime by a
config string (a rule_type, a strategy_type, a source_type); nothing in
the roadmap ever swaps orchestrators the same way. A Protocol with exactly
one implementor and no registry is indirection without payoff, so this is
a plain concrete class instead. Extracting a Protocol later (if a second
implementation — an async orchestrator, a batch one — ever legitimately
shows up) is a small, additive change, not a rewrite.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sentinel.datasources import DataSource
from sentinel.domain import Dataset, Policy, QualityEvent, Status, ValidationRun
from sentinel.rules import get_rule
from sentinel.thresholds import get_threshold_strategy

_STATUS_SEVERITY: dict[Status, int] = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}


def _worst_status(statuses: Iterable[Status]) -> Status:
    """The most severe of a set of statuses (FAIL worst, then WARN, then
    PASS). Defaults to PASS for an empty iterable — a run with no events
    has nothing to be unhappy about, though in practice Policy always
    requires at least one rule, so run() never actually exercises that
    default.
    """
    worst = Status.PASS
    for status in statuses:
        if _STATUS_SEVERITY[status] > _STATUS_SEVERITY[worst]:
            worst = status
    return worst


class ValidationOrchestrator:
    """Coordinates one Policy's execution against one Dataset (FR-06).

    Stateless: nothing about a single run is held on ``self`` between
    calls, so one instance can safely run many (dataset, policy, source)
    combinations. Rule and ThresholdStrategy lookup failures
    (RuleNotRegisteredError, ThresholdStrategyNotRegisteredError) are
    allowed to propagate rather than being wrapped in an orchestrator-
    specific error — introducing a unified error type now, before a caller
    (Milestone 2's CLI) exists to say what it actually needs from one,
    would be guessing.
    """

    def run(self, dataset: Dataset, policy: Policy, source: DataSource) -> ValidationRun:
        started_at = datetime.now(UTC)

        events: list[QualityEvent] = []
        for rule_config in policy.rules:
            rule = get_rule(rule_config.rule_type)
            metric = rule.compute(source, rule_config)

            strategy = get_threshold_strategy(rule_config.threshold.strategy)
            threshold_result = strategy.evaluate(metric, rule_config.threshold)

            events.append(
                QualityEvent(
                    severity=rule_config.severity,
                    blocking=rule_config.blocking,
                    metric=metric,
                    threshold_result=threshold_result,
                )
            )

        finished_at = datetime.now(UTC)

        return ValidationRun(
            dataset=dataset,
            policy_version=policy.version,
            started_at=started_at,
            finished_at=finished_at,
            status=_worst_status(event.status for event in events),
            quality_events=tuple(events),
        )
