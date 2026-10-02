"""Incident: how urgently one failed QualityEvent needs attention.

Chain: Rule -> Metric -> ThresholdResult -> QualityEvent -> Incident. Only
created for non-PASS events. Frozen, so later config changes don't rewrite past
conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sentinel.domain.events import QualityEvent


class IncidentPriority(StrEnum):
    """Computed priority of an Incident.

    A separate type from Severity and Criticality (the inputs), even though the
    values overlap.
    """

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class IncidentScoreComponents:
    """The five 0-100 inputs to the score.

    Kept separately so each Incident can explain its priority.
    """

    severity_score: float
    criticality_score: float
    deviation_score: float
    frequency_score: float
    confidence_score: float


@dataclass(frozen=True)
class Incident:
    """Prioritized view of one failed QualityEvent.

    ``score`` is the weighted sum of ``components`` (0-100); ``priority`` is that
    score mapped through PriorityThresholds; ``reasons`` are short human-readable
    explanation lines.
    """

    quality_event: QualityEvent
    priority: IncidentPriority
    score: float
    components: IncidentScoreComponents
    reasons: tuple[str, ...]
