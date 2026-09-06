"""Run-time facts: what a Threshold Strategy decided (ThresholdResult), what
a Rule's evaluation amounted to once judged (QualityEvent), and what one
Policy execution against one Dataset produced overall (ValidationRun).

All three are frozen dataclasses, and QualityEvent/ValidationRun compose
rather than duplicate. QualityEvent doesn't store its own copy of "actual"
and "expected" the way the PRD's flat quality_events table does — it holds
a Metric and a ThresholdResult and exposes ``actual``/``expected``/``status``
as read-only properties over them. That flat view is a real requirement
(Milestone 2's persistence layer will want exactly those columns), but it's
a projection of this object, not this object's storage layout. Keeping the
two separate is what let Metric stay ignorant of thresholds and
ThresholdResult stay ignorant of severity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sentinel.domain.dataset import Dataset
from sentinel.domain.metric import Metric

if TYPE_CHECKING:
    # Deferred: sentinel.domain.incident imports QualityEvent from this module,
    # so importing Incident here at module load time would be circular. Safe as
    # a type-checking-only import because `from __future__ import annotations`
    # already makes every annotation in this file a lazily-evaluated string.
    from sentinel.domain.incident import Incident


class Status(StrEnum):
    """The verdict a ThresholdStrategy reaches about a Metric, and the
    aggregate outcome of a ValidationRun. Distinct from Severity: Status is
    computed at evaluation time; Severity is declared in the policy."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class Severity(StrEnum):
    """How seriously a failed rule should be taken (FR-11). Set once, in
    the policy's RuleConfig — not computed, unlike Status."""

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ThresholdResult:
    """The output of ThresholdStrategy.evaluate(): a verdict plus enough
    context to explain it. ``expected`` is a human-readable description
    (e.g. "row_count >= 1000"), not a structured value — different
    strategies express "what was expected" too differently (a fixed bound
    vs. a percentage band vs. a statistical interval) to force into one
    shape yet. Revisit if a consumer needs it structured.

    ``details`` (Milestone 4) is that revisit, for the strategies that
    need it: a JSON-encoded string carrying an adaptive strategy's
    computed baseline, bounds, deviation, and sample size — the same
    answer Milestone 3 gave ``Metric`` for the identical problem
    (see ``Metric.details``'s own docstring). ``expected`` stays the
    short human-readable line; ``details`` is the machine-readable
    backing data behind it. Optional and ``None`` by default —
    ``StaticThresholdStrategy`` and every strategy that predates
    Milestone 4 leaves it unset, same as every Milestone 0/1 rule left
    ``Metric.details`` unset. Not persisted this milestone either (no
    ``quality_events.details`` column) — visible on the in-memory
    QualityEvent for the CLI and the synthetic experiment framework,
    exactly the scope ``Metric.details`` shipped with in Milestone 3.
    """

    status: Status
    expected: str
    strategy_type: str
    details: str | None = None


@dataclass(frozen=True)
class QualityEvent:
    """One rule's evaluation outcome within a run: a measurement (Metric),
    a judgment of that measurement (ThresholdResult), and the policy
    decisions that applied to this rule — severity, and whether a failure
    here blocks the calling pipeline (FR-12).

    ``blocking`` was added while building the orchestrator (Task 7), not
    at this dataclass's original authoring (Task 2): RuleConfig has always
    carried it, but nothing captured it once a rule was actually evaluated,
    which meant the information FR-12 requires would have been silently
    lost by the time anyone inspected a ValidationRun. Same reasoning as
    ``severity`` — copied from the RuleConfig at assembly time, since a
    QualityEvent shouldn't require walking back to the Policy to know how
    it should be treated.
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
        """Passthrough to ``Metric.details`` (Milestone 3), mirroring
        ``actual``/``expected``/``status`` exactly: a QualityEvent
        shouldn't require reaching back into its own ``metric`` field to
        read structured context a Rule attached. ``None`` for every
        Milestone 0/1 rule, which never set it."""
        return self.metric.details

    @property
    def threshold_details(self) -> str | None:
        """Passthrough to ``ThresholdResult.details`` (Milestone 4) — the
        adaptive-strategy counterpart to ``details`` above. Kept as a
        separate property, not folded into ``details``, because the two
        answer different questions: ``details`` is what a Rule *observed*
        (e.g. a schema diff); ``threshold_details`` is how a
        ThresholdStrategy *judged* it (a baseline, bounds, a deviation).
        ``None`` for every strategy that predates Milestone 4, and for
        Static, which never sets it."""
        return self.threshold_result.details


@dataclass(frozen=True)
class ValidationRun:
    """One execution of a Policy against a Dataset.

    Holds the full Dataset object rather than a bare dataset_id: at
    Milestone 0/1 there's no dataset registry to look one up from, and the
    orchestrator already has the Dataset in hand (see the
    ValidationOrchestrator.run signature). Milestone 2's persistence layer
    is the natural place to collapse this to a foreign key when a
    ValidationRun actually needs to be written as a database row — that's a
    storage-layer translation, not a reason to weaken this object now.

    ``status`` is a required field, not computed here: aggregating
    "worst status across quality_events" is behavior, and this module holds
    no behavior. That aggregation belongs to whatever assembles this object
    (the ValidationOrchestrator, Milestone 0's Task 7).

    ``incidents`` (Milestone 5) holds one Incident per non-PASS QualityEvent
    in ``quality_events`` -- see sentinel.domain.incident's own docstring for
    why only non-PASS events are prioritized. Defaults to ``()`` so every
    Milestone 0-4 construction site (including every existing test) keeps
    building a ValidationRun without this argument and is unaffected; the
    ValidationOrchestrator (Milestone 5) is the only caller that populates it
    for real.
    """

    dataset: Dataset
    policy_version: str
    started_at: datetime
    finished_at: datetime
    status: Status
    quality_events: tuple[QualityEvent, ...]
    incidents: tuple[Incident, ...] = ()
