"""Metric: one measurement produced by a Rule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Metric:
    """A value a Rule computed, before any pass/fail judgment.

    ``value`` is what thresholds evaluate. ``details`` is optional JSON context
    (e.g. a schema diff) for reporting only; it never affects pass/fail.
    """

    metric_name: str
    value: float
    computed_at: datetime
    details: str | None = None
