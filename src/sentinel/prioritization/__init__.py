"""Incident Prioritization (Milestone 5): turns a non-PASS QualityEvent
into an explainable Incident by combining validation severity, dataset
criticality, deviation magnitude, historical failure frequency, and
anomaly confidence into one deterministic, weighted score.

See docs/architecture/0006-milestone-5-design.md for the full design
review this package implements, and IncidentPrioritizer (prioritizer.py)
for the one entry point ValidationOrchestrator calls.
"""

from sentinel.prioritization.config import (
    DEFAULT_INCIDENT_PRIORITIZATION_CONFIG,
    IncidentPrioritizationConfig,
    PriorityThresholds,
    ScoreWeights,
)
from sentinel.prioritization.frequency import FailureHistory, summarize
from sentinel.prioritization.history import FailureHistorySource, NullFailureHistorySource
from sentinel.prioritization.prioritizer import IncidentPrioritizer

__all__ = [
    "DEFAULT_INCIDENT_PRIORITIZATION_CONFIG",
    "FailureHistory",
    "FailureHistorySource",
    "IncidentPrioritizationConfig",
    "IncidentPrioritizer",
    "NullFailureHistorySource",
    "PriorityThresholds",
    "ScoreWeights",
    "summarize",
]
