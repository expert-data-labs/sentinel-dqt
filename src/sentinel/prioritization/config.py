"""Configuration for incident prioritization: the scoring weights and
priority boundaries every Incident is computed against.

A plain, code-level frozen dataclass with class-level defaults --
deliberately *not* a pydantic model loaded from per-dataset Policy YAML,
even though the milestone brief's own sketch shows
``incident_prioritization:`` nested in what looks like a policy file. See
docs/architecture/0006-milestone-5-design.md Part 9 for the full reasoning;
the short version: these weights and boundaries are what make "CRITICAL"
mean the same thing everywhere in the system. If each dataset's policy
could redefine them, two datasets' CRITICAL incidents would stop being
comparable -- the same reason Severity and Criticality themselves are kept
un-conflated, one level up. This is also directly responsive to the
brief's own instruction to "avoid configuration explosion" and "first
evaluate whether all of these values actually need to be configurable" --
nothing yet has demonstrated a need for per-dataset overrides.

Promoting this to a loadable YAML file later (via the existing
``load_yaml_model`` helper sentinel.config_loading already provides for
Dataset and Policy) is a small, additive change if a real cross-dataset
tuning need ever shows up -- not a rewrite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sentinel.domain.incident import IncidentPriority


class IncidentPrioritizationConfigError(Exception):
    """A ScoreWeights or PriorityThresholds value is internally
    inconsistent (weights that don't sum to 1.0, or thresholds that aren't
    strictly increasing) -- raised at construction time, not silently
    normalized, since a scoring model that quietly renormalizes wrong
    weights would hide a real configuration mistake."""


@dataclass(frozen=True)
class ScoreWeights:
    """The five weights the weighted-additive scoring model
    (sentinel.prioritization.scoring) combines
    IncidentScoreComponents with. Must sum to 1.0 (validated at
    construction) so a component score already normalized to 0-100
    produces a final score in the same 0-100 range with no separate
    clamping step needed anywhere.

    Defaults (0.30 / 0.30 / 0.20 / 0.10 / 0.10): severity and criticality
    intentionally dominate at 60% combined -- they're the two
    business-declared inputs (what severity was this rule configured with;
    how important is this dataset), and deviation/frequency/confidence
    refine within that band rather than override it. These are a proposed
    starting point, not derived from anything -- see the milestone design
    doc's Part 8 for the comparison against multiplicative/hybrid
    alternatives, and Part 13 for the seven scenarios these should be
    validated against.
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
    """The three score cut-points separating INFO/WARNING/HIGH/CRITICAL.
    ``warning_at``/``high_at``/``critical_at`` are the score a component
    sum must reach *at or above* to earn that priority (matching the
    milestone brief's own 0-24/25-49/50-74/75-100 example: ``warning_at``
    corresponds to 25, ``high_at`` to 50, ``critical_at`` to 75) -- an
    unvalidated starting point, to be adjusted once the seven test
    scenarios (design doc Part 13) show where they actually should sit.
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
        """The IncidentPriority ``score`` (already a weighted sum in
        [0, 100] -- see sentinel.prioritization.scoring.aggregate_score)
        falls into."""
        if score >= self.critical_at:
            return IncidentPriority.CRITICAL
        if score >= self.high_at:
            return IncidentPriority.HIGH
        if score >= self.warning_at:
            return IncidentPriority.WARNING
        return IncidentPriority.INFO


@dataclass(frozen=True)
class IncidentPrioritizationConfig:
    """Everything IncidentPrioritizer (sentinel.prioritization.prioritizer)
    needs to turn IncidentScoreComponents into a score and priority."""

    weights: ScoreWeights = field(default_factory=ScoreWeights)
    thresholds: PriorityThresholds = field(default_factory=PriorityThresholds)


DEFAULT_INCIDENT_PRIORITIZATION_CONFIG = IncidentPrioritizationConfig()
