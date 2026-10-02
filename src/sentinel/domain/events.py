"""Run-time facts: ThresholdResult, QualityEvent and ValidationRun.

QualityEvent wraps a Metric and a ThresholdResult and exposes ``actual``,
``expected`` and ``status`` as properties instead of copying them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sentinel.domain.dataset import Dataset
from sentinel.domain.metric import Metric

if TYPE_CHECKING:
    # Type-only import: incident.py imports this module (avoids a cycle).
    from sentinel.domain.incident import Incident


class Status(StrEnum):
    """Outcome of evaluating a Metric (and of a whole run). Computed, unlike
    Severity.
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class Severity(StrEnum):
    """How seriously a failed rule should be taken. Declared in the policy."""

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ThresholdResult:
    """A strategy's verdict on a Metric.

    ``expected`` is a short human-readable description (e.g. "row_count >= 1000").
    ``details`` is optional JSON with the computed baseline, bounds and sample
    size (set by adaptive strategies).
    """

    status: Status
    expected: str
    strategy_type: str
    details: str | None = None


@dataclass(frozen=True)
class QualityEvent:
    """One rule's outcome in a run: Metric + ThresholdResult + policy settings.

    ``severity`` and ``blocking`` are copied from the RuleConfig so the event is
    self-contained.
    """

    severity: Severity
    blocking: bool
    metric: Metric
    threshold_result: ThresholdResult

    @property
    def rule_name(self) -> str:
        return self.metric.metric_name

    @property
    def actual(self) -> float:
        return self.metric.value

    @property
    def expected(self) -> str:
        return self.threshold_result.expected

    @property
    def status(self) -> Status:
        return self.threshold_result.status

    @property
    def details(self) -> str | None:
        """The Metric's details (what the rule observed)."""
        return self.metric.details

    @property
    def threshold_details(self) -> str | None:
        """The ThresholdResult's details (how the strategy judged it)."""
        return self.threshold_result.details


@dataclass(frozen=True)
class ValidationRun:
    """One execution of a Policy against a Dataset.

    ``status`` is the worst status across ``quality_events`` (set by the
    orchestrator). ``incidents`` holds one Incident per non-PASS event.
    """

    dataset: Dataset
    policy_version: str
    started_at: datetime
    finished_at: datetime
    status: Status
    quality_events: tuple[QualityEvent, ...]
    incidents: tuple[Incident, ...] = ()
