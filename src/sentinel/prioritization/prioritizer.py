"""IncidentPrioritizer: the one entry point that turns a non-PASS
QualityEvent into an explainable Incident.

A plain concrete class, not a Protocol with a registry -- the same call
ValidationOrchestrator itself already made for the identical reason (see
its own docstring): a Protocol/registry earns its keep when multiple
implementations are selected at runtime by a config string. There is one
incident-prioritization algorithm here, tuned by
IncidentPrioritizationConfig, not several interchangeable ones chosen per
dataset. See docs/architecture/0006-milestone-5-design.md Part 2.

This is the only place that wires together every other module in this
package (deviation, frequency, confidence, scoring, config) into one
result -- everything it calls is a pure function or a plain value object,
so this class itself has almost no logic of its own beyond sequencing and
building the human-readable ``reasons``.
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
    """Scores and explains one non-PASS QualityEvent, given the Dataset it
    belongs to and that (dataset, rule) pair's prior outcomes.

    Stateless with respect to any single call -- like ValidationOrchestrator,
    ``self`` only holds ``config`` for the lifetime of the instance (a
    dependency, not per-call state), so one instance safely prioritizes many
    events.
    """

    def __init__(self, config: IncidentPrioritizationConfig | None = None) -> None:
        self._config = config if config is not None else DEFAULT_INCIDENT_PRIORITIZATION_CONFIG

    def prioritize(
        self,
        dataset: Dataset,
        event: QualityEvent,
        failure_outcomes: Sequence[Status] = (),
    ) -> Incident:
        """Build an Incident for ``event`` (a non-PASS QualityEvent
        produced against ``dataset``), given ``failure_outcomes`` -- that
        (dataset, rule) pair's prior evaluation outcomes, most recent
        first, exactly as FailureHistorySource.get_outcomes returns them
        (sentinel.prioritization.history). Interpreting those raw outcomes
        into occurrences/streaks/first-occurrence is this method's own
        job (via sentinel.prioritization.frequency.summarize), the same
        division of labor a ThresholdStrategy already has for raw
        ``history: Sequence[Metric]``.

        Raises ValueError if ``event.status is Status.PASS`` -- there is
        nothing to prioritize about a check that passed (see
        sentinel.domain.incident's own docstring for why); a caller
        (ValidationOrchestrator) is expected to only call this for
        non-PASS events in the first place, so this is a defensive
        assertion, not an expected code path.
        """
        if event.status is Status.PASS:
            raise ValueError(
                "IncidentPrioritizer.prioritize() called for a PASS QualityEvent "
                f"({event.rule_name!r}); only non-PASS events are prioritized "
                "(docs/architecture/0006-milestone-5-design.md Part 3)."
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
    """Human-readable explanation lines, built directly from the same
    facts and component inputs the score was computed from -- never
    reverse-engineered from the score after the fact (see Incident's own
    docstring). Matches the shape of the sample output in
    docs/architecture/0006-milestone-5-design.md Part 11.
    """
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
