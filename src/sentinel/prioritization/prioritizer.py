"""IncidentPrioritizer: turns a failed QualityEvent into an explained Incident.

Combines the deviation, frequency, confidence and scoring modules. A plain
class: there is only one prioritization algorithm, tuned by config.
"""

from __future__ import annotations

from collections.abc import Sequence

from sentinel.domain import Dataset, QualityEvent, Status
from sentinel.domain.incident import Incident, IncidentScoreComponents
from sentinel.prioritization import scoring
from sentinel.prioritization.confidence import compute_confidence, extract_n_history
from sentinel.prioritization.config import (
    DEFAULT_INCIDENT_PRIORITIZATION_CONFIG,
    IncidentPrioritizationConfig,
)
from sentinel.prioritization.deviation import compute_deviation_ratio
from sentinel.prioritization.frequency import FailureHistory, summarize


class IncidentPrioritizer:
    """Scores and explains failed QualityEvents. Holds only its config."""

    def __init__(self, config: IncidentPrioritizationConfig | None = None) -> None:
        self._config = config if config is not None else DEFAULT_INCIDENT_PRIORITIZATION_CONFIG

    def prioritize(
        self,
        dataset: Dataset,
        event: QualityEvent,
        failure_outcomes: Sequence[Status] = (),
    ) -> Incident:
        """Build an Incident for a non-PASS ``event``.

        ``failure_outcomes`` are the rule's prior statuses, most recent first.
        Raises ValueError for a PASS event.
        """
        if event.status is Status.PASS:
            raise ValueError(
                "IncidentPrioritizer.prioritize() called for a PASS QualityEvent "
                f"({event.rule_name!r}); only non-PASS events are prioritized."
            )

        failure_history = summarize(failure_outcomes)
        deviation_ratio = compute_deviation_ratio(event.threshold_result)
        confidence = compute_confidence(event.threshold_result, failure_history)

        components = IncidentScoreComponents(
            severity_score=scoring.severity_score(event.severity),
            criticality_score=scoring.criticality_score(dataset.criticality),
            deviation_score=scoring.deviation_score(deviation_ratio),
            frequency_score=scoring.frequency_score(failure_history),
            confidence_score=scoring.confidence_score(confidence),
        )
        score = scoring.aggregate_score(components, self._config.weights)
        priority = self._config.thresholds.classify(score)

        reasons = _build_reasons(
            dataset=dataset,
            event=event,
            failure_history=failure_history,
            deviation_ratio=deviation_ratio,
            confidence=confidence,
        )

        return Incident(
            quality_event=event,
            priority=priority,
            score=score,
            components=components,
            reasons=reasons,
        )


def _build_reasons(
    *,
    dataset: Dataset,
    event: QualityEvent,
    failure_history: FailureHistory,
    deviation_ratio: float | None,
    confidence: float,
) -> tuple[str, ...]:
    """Human-readable explanation lines, built from the same inputs as the score."""
    reasons = [
        f"Dataset criticality: {dataset.criticality.value.upper()}",
        f"Validation severity: {event.severity.value.upper()}",
        _deviation_reason(event, deviation_ratio),
        _frequency_reason(failure_history),
        _confidence_reason(event, confidence),
    ]
    return tuple(reasons)


def _deviation_reason(event: QualityEvent, deviation_ratio: float | None) -> str:
    strategy_type = event.threshold_result.strategy_type
    if deviation_ratio is None:
        return f"Deviation: unavailable for strategy {strategy_type!r} (no details recorded)"
    return f"Deviation: {deviation_ratio:.0%} of the tolerance edge (strategy: {strategy_type})"


def _frequency_reason(history: FailureHistory) -> str:
    if history.is_first_occurrence:
        if history.total_observations == 0:
            return "Failure frequency: first-ever recorded evaluation of this rule"
        return (
            "Failure frequency: first recorded failure "
            f"(0 prior failures in the last {history.total_observations} observations)"
        )
    return (
        f"Failure frequency: {history.occurrences} occurrence(s) in the last "
        f"{history.total_observations} observations "
        f"({history.consecutive_failures} consecutive)"
    )


def _confidence_reason(event: QualityEvent, confidence: float) -> str:
    strategy_type = event.threshold_result.strategy_type
    n_history = extract_n_history(event.threshold_result)
    n_history_display = "n/a" if n_history is None else str(n_history)
    return f"Anomaly confidence: {confidence:.2f} ({strategy_type}, n={n_history_display})"
