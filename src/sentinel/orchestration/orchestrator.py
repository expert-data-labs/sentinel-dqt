"""ValidationOrchestrator: runs a Policy's rules against a DataSource.

For each rule: compute the Metric, fetch its history, evaluate the threshold,
build a QualityEvent, and prioritize it into an Incident if it didn't pass. A
plain class (not a Protocol) because there is only one implementation.
"""

from __future__ import annotations

from collections.abc import Iterable

from sentinel import clock
from sentinel.datasources import DataSource
from sentinel.domain import Dataset, Incident, Policy, QualityEvent, Status, ValidationRun
from sentinel.prioritization import (
    FailureHistorySource,
    IncidentPrioritizer,
    NullFailureHistorySource,
)
from sentinel.rules import get_rule
from sentinel.thresholds import HistoricalMetricsSource, NullHistorySource, get_threshold_strategy

_STATUS_SEVERITY: dict[Status, int] = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}


def _worst_status(statuses: Iterable[Status]) -> Status:
    """Most severe status (FAIL > WARN > PASS). PASS if empty."""
    worst = Status.PASS
    for status in statuses:
        if _STATUS_SEVERITY[status] > _STATUS_SEVERITY[worst]:
            worst = status
    return worst


class ValidationOrchestrator:
    """Runs one Policy against one Dataset.

    Holds no per-run state, so one instance can run many validations.
    Dependencies are optional and default to no-history sources and the default
    IncidentPrioritizer. Registry lookup errors propagate unchanged.
    """

    def __init__(
        self,
        history_source: HistoricalMetricsSource | None = None,
        failure_history_source: FailureHistorySource | None = None,
        prioritizer: IncidentPrioritizer | None = None,
    ) -> None:
        self._history_source = (
            history_source if history_source is not None else NullHistorySource()
        )
        self._failure_history_source = (
            failure_history_source
            if failure_history_source is not None
            else NullFailureHistorySource()
        )
        self._prioritizer = prioritizer if prioritizer is not None else IncidentPrioritizer()

    def run(self, dataset: Dataset, policy: Policy, source: DataSource) -> ValidationRun:
        started_at = clock.now()

        events: list[QualityEvent] = []
        incidents: list[Incident] = []
        for rule_config in policy.rules:
            rule = get_rule(rule_config.rule_type)
            metric = rule.compute(source, rule_config)

            history = self._history_source.get_history(dataset.id, rule_config.name)

            strategy = get_threshold_strategy(rule_config.threshold.strategy)
            threshold_result = strategy.evaluate(metric, rule_config.threshold, history)

            event = QualityEvent(
                severity=rule_config.severity,
                blocking=rule_config.blocking,
                metric=metric,
                threshold_result=threshold_result,
            )
            events.append(event)

            # Only failed/warned checks become Incidents.
            if event.status is not Status.PASS:
                failure_outcomes = self._failure_history_source.get_outcomes(
                    dataset.id, rule_config.name
                )
                incidents.append(self._prioritizer.prioritize(dataset, event, failure_outcomes))

        finished_at = clock.now()

        return ValidationRun(
            dataset=dataset,
            policy_version=policy.version,
            started_at=started_at,
            finished_at=finished_at,
            status=_worst_status(event.status for event in events),
            quality_events=tuple(events),
            incidents=tuple(incidents),
        )
