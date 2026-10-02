"""Incident prioritization.

Turns a non-PASS QualityEvent into an Incident with a weighted score built from
severity, dataset criticality, deviation, failure frequency and confidence.
Entry point: IncidentPrioritizer.
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
