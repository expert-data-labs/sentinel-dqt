"""Scoring weights and priority cut-offs for incident prioritization.

Defined in code, not per-dataset YAML, so a CRITICAL incident means the same
thing for every dataset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sentinel.domain.incident import IncidentPriority


class IncidentPrioritizationConfigError(Exception):
    """Weights don't sum to 1.0, or thresholds aren't strictly increasing."""


@dataclass(frozen=True)
class ScoreWeights:
    """Weights for the five score components. Must sum to 1.0.

    Severity and criticality get 60% between them; deviation, frequency and
    confidence adjust within that.
    """

    severity: float = 0.30
    criticality: float = 0.30
    deviation: float = 0.20
    frequency: float = 0.10
    confidence: float = 0.10

    def __post_init__(self) -> None:
        total = (
            self.severity + self.criticality + self.deviation + self.frequency + self.confidence
        )
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise IncidentPrioritizationConfigError(
                f"ScoreWeights must sum to 1.0, got {total!r}: {self!r}"
            )


@dataclass(frozen=True)
class PriorityThresholds:
    """Minimum score for each priority (defaults: 25 / 50 / 75).

    Below ``warning_at`` is INFO.
    """

    warning_at: float = 25.0
    high_at: float = 50.0
    critical_at: float = 75.0

    def __post_init__(self) -> None:
        if not (0 < self.warning_at < self.high_at < self.critical_at):
            raise IncidentPrioritizationConfigError(
                "PriorityThresholds must satisfy "
                f"0 < warning_at < high_at < critical_at, got "
                f"warning_at={self.warning_at!r}, high_at={self.high_at!r}, "
                f"critical_at={self.critical_at!r}"
            )

    def classify(self, score: float) -> IncidentPriority:
        """Map a 0-100 score to an IncidentPriority."""
        if score >= self.critical_at:
            return IncidentPriority.CRITICAL
        if score >= self.high_at:
            return IncidentPriority.HIGH
        if score >= self.warning_at:
            return IncidentPriority.WARNING
        return IncidentPriority.INFO


@dataclass(frozen=True)
class IncidentPrioritizationConfig:
    """Weights and thresholds used by IncidentPrioritizer."""

    weights: ScoreWeights = field(default_factory=ScoreWeights)
    thresholds: PriorityThresholds = field(default_factory=PriorityThresholds)


DEFAULT_INCIDENT_PRIORITIZATION_CONFIG = IncidentPrioritizationConfig()
