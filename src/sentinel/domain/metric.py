"""Metric: one measurement, produced by a Rule.

Deliberately minimal for Milestone 0/1. A ``dimensions`` field (for tagging
a metric with the column or segment it applies to) was considered and cut:
none of Milestone 1's three rules (row count, null rate, uniqueness) needed
it, and adding it then would have meant solving "how do you keep a dict
immutable inside a frozen dataclass" for a feature nothing used yet.

Milestone 3's Schema Validation rule is that concrete need arriving:
``value`` alone (a single float) can express *how many* schema differences
were found — enough for ``StaticThresholdStrategy`` to keep evaluating it
exactly as it always has — but not *which* columns are missing, unexpected,
or type-mismatched. ``details`` is the smallest field that closes that gap
without reopening the frozen-mutable-dict question: a ``str`` (a
JSON-encoded structured diff, for this milestone's one caller) is
immutable by type, so no new immutable-collection machinery is needed.
It's optional and defaults to ``None`` — every Milestone 0/1 rule leaves it
unset, and nothing about ``Metric``'s existing meaning changes for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Metric:
    """A single computed value: what a Rule found, before any judgment
    about whether that value is acceptable (see ThresholdResult).

    ``value`` is always the number a ThresholdStrategy evaluates —
    unchanged by ``details``' presence. ``details``, when a Rule sets it,
    is optional structured context that flows through to QualityEvent
    (see its ``details`` property) for reporting, but never participates
    in the pass/fail judgment itself; that stays exactly value-vs-threshold,
    same as every other rule.
    """

    metric_name: str
    value: float
    computed_at: datetime
    details: str | None = None
