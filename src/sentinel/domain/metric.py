"""Metric: one measurement, produced by a Rule.

Deliberately minimal for Milestone 0/1. A ``dimensions`` field (for tagging
a metric with the column or segment it applies to) was considered and cut:
none of Milestone 1's three rules (row count, null rate, uniqueness) need
it, and adding it now would mean solving "how do you keep a dict immutable
inside a frozen dataclass" for a feature nothing uses yet. Add it back when
a concrete rule (freshness or schema, in Milestone 3) actually needs to
carry extra context — that's a small, additive change to one file, not a
redesign.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Metric:
    """A single computed value: what a Rule found, before any judgment
    about whether that value is acceptable (see ThresholdResult)."""

    metric_name: str
    value: float
    computed_at: datetime
