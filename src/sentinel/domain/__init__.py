"""Domain objects: config-time definitions and run-time facts.

No behavior lives here — only structure. Dataset is a pydantic model (an
external-input boundary: registration fields are human-entered, FR-01).
Metric, ValidationRun, QualityEvent, and ThresholdResult are frozen
dataclasses: immutable facts produced by execution, with no external input
to validate.
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
