"""Domain objects. Structure only, no behavior.

Dataset and Policy are pydantic models (validated user input). Run-time facts
(Metric, ValidationRun, QualityEvent, ThresholdResult) are frozen dataclasses.
"""

from sentinel.domain.dataset import Criticality, Dataset
from sentinel.domain.events import (
    QualityEvent,
    Severity,
    Status,
    ThresholdResult,
    ValidationRun,
)
from sentinel.domain.incident import Incident, IncidentPriority, IncidentScoreComponents
from sentinel.domain.metric import Metric
from sentinel.domain.policy import Policy, RuleConfig, ThresholdConfig

__all__ = [
    "Criticality",
    "Dataset",
    "Incident",
    "IncidentPriority",
    "IncidentScoreComponents",
    "Metric",
    "Policy",
    "QualityEvent",
    "RuleConfig",
    "Severity",
    "Status",
    "ThresholdConfig",
    "ThresholdResult",
    "ValidationRun",
]
