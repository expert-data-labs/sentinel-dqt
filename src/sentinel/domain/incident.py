"""Incident: how urgently one QualityEvent needs attention.

This is the fourth layer in the Rule -> Metric -> ThresholdStrategy ->
QualityEvent -> Incident Prioritization chain (Milestone 5). Each layer
answers a different question about the same underlying occurrence:

    Rule              -> what did we observe?              (Metric)
    ThresholdStrategy  -> is this observation anomalous?     (ThresholdResult)
    QualityEvent       -> what does that verdict mean here?  (severity, blocking)
    Incident           -> how important is this, right now?  (priority, score)

Incident holds a reference to the QualityEvent it prioritizes rather than
duplicating its fields, the same compositional pattern QualityEvent itself
uses for Metric and ThresholdResult (see domain/events.py's own module
docstring) -- an Incident should never require its own copy of "status" or
"severity" that could drift out of sync with the QualityEvent it's about.

Frozen, like every other domain fact in this codebase (Metric,
ThresholdResult, QualityEvent, ValidationRun): what Sentinel concluded
about an Incident's priority at validation time must not change later just
because incident_prioritization's configured weights or thresholds change
afterward. A re-run under new configuration produces a new Incident, not a
mutation of an old one.

Only produced for a QualityEvent whose status is not PASS (see
docs/architecture/0006-milestone-5-design.md Part 3 and Part 12, question
1) -- there is nothing to prioritize about a check that passed, and
"first occurrence" / historical-frequency reasoning (sentinel.prioritization
.frequency) is defined in terms of prior failures, not prior evaluations
in general.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sentinel.domain.events import QualityEvent


class IncidentPriority(StrEnum):
    """The final, computed operational priority of an Incident.

    Deliberately a distinct type from Severity (domain/events.py) and from
    Criticality (domain/dataset.py), even though all three enums currently
    share overlapping string vocabulary (info/warning/high/critical for
    Priority and Severity; low/medium/high/critical for Criticality). This
    extends a distinction the codebase already draws once: Criticality's
    own docstring separates itself from Severity because "conflating them
    would make it impossible to say 'a HIGH severity rule on a LOW
    criticality dataset'". IncidentPriority is that combination's *output*
    -- a third, runtime-computed concept, distinct from both of the
    config-time inputs that feed it. Reusing Severity's enum type here
    would make it impossible to tell "the policy author configured this
    rule as HIGH severity" apart from "Sentinel computed HIGH priority for
    this specific occurrence, after weighing severity against everything
    else" -- and those routinely differ (see the seven scenarios in
    docs/architecture/0006-milestone-5-design.md Part 8/Part 13).
    """

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class IncidentScoreComponents:
    """The five inputs to the scoring model (sentinel.prioritization.scoring),
    each already normalized to a common 0-100 scale before this object is
    built.

    Kept individually, not collapsed into just the final score, because
    this -- not a reverse-engineered breakdown of the total -- is what
    makes an Incident explainable (Incident.reasons is built directly from
    these, see sentinel.prioritization.prioritizer). See
    docs/architecture/0006-milestone-5-design.md Part 8 for why a weighted
    additive model over these five components was chosen over a
    multiplicative or hybrid one.
    """

    severity_score: float
    criticality_score: float
    deviation_score: float
    frequency_score: float
    confidence_score: float


@dataclass(frozen=True)
class Incident:
    """What Sentinel concluded, at validation time, about how urgently one
    QualityEvent needs attention (Milestone 5).

    ``score`` is the weighted sum of ``components`` (0-100, already
    rounded for display -- see sentinel.prioritization.scoring), and
    ``priority`` is that score classified against the configured
    boundaries (sentinel.prioritization.config.PriorityThresholds).
    ``reasons`` is a tuple of short, human-readable lines explaining the
    priority in the same terms it was computed in (see the sample output
    in docs/architecture/0006-milestone-5-design.md Part 11) -- never
    reverse-engineered from ``score`` after the fact, since ``components``
    already holds everything a reason line needs.
    """

    quality_event: QualityEvent
    priority: IncidentPriority
    score: float
    components: IncidentScoreComponents
    reasons: tuple[str, ...]
