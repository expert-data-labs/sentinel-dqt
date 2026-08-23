"""The config-time definition half of a Policy: what an engineer declares in
a YAML file (FR-02), before Sentinel does anything with it.

Policy, RuleConfig, and ThresholdConfig share one property that Dataset also
has: every field here was typed by a human and needs pydantic's kind of
validation, not the kind a frozen dataclass gives you.

ThresholdConfig is the config-time half of the Threshold definition/
evaluation split described in the Milestone 0 architecture doc. It is
deliberately thin: a ``strategy`` name plus an open ``params`` mapping,
rather than a field for every bound any strategy might ever need (``min``,
``max``, ``max_duplicates``, ``max_delay_minutes`` today; a percentage band
or a sigma multiplier once Milestone 4 lands). Making ThresholdConfig grow a
field per strategy would mean editing this shared schema every time a new
ThresholdStrategy is added — exactly the kind of central-branch-point the
registry pattern (Task 4/5) exists to avoid. Interpreting and validating
``params`` is each concrete ThresholdStrategy's own job, done against its
own contract, when it runs.

RuleConfig follows the same logic for ``column``: some rule types need one
(null_rate, uniqueness, freshness), volume/row_count doesn't. A single
optional field is simpler than a discriminated union keyed by rule type, and
it costs nothing today — a Rule implementation that needs a column just
reads it and raises a clear error if it's missing, same as a
ThresholdStrategy would for a missing param.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel.domain.events import Severity


class ThresholdConfig(BaseModel):
    """The declared, config-time half of a Threshold (see module docstring).

    Accepts the PRD's flat YAML shape directly —
    ``{strategy: static, min: 1000}`` — and reshapes it internally into
    ``strategy`` + ``params`` so every bound-carrying key doesn't need its
    own field here.
    """

    model_config = ConfigDict(frozen=True)

    strategy: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_unknown_keys_into_params(cls, data: Any) -> Any:
        if isinstance(data, dict) and "params" not in data:
            data = dict(data)
            return {"strategy": data.pop("strategy", None), "params": data}
        return data


class RuleConfig(BaseModel):
    """One rule's declaration inside a Policy.

    ``rule_type`` is populated from the YAML key ``type`` (aliased) — kept
    as ``rule_type`` internally so it matches the vocabulary the Rule
    Protocol itself uses (``Rule.rule_type``, Task 4), rather than shadowing
    the ``type`` builtin in every place this field gets read in code.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str = Field(min_length=1)
    rule_type: str = Field(min_length=1, alias="type")
    column: str | None = None
    severity: Severity = Severity.WARNING
    blocking: bool = True
    threshold: ThresholdConfig


class Policy(BaseModel):
    """A versioned, declarative set of quality expectations for a dataset
    (FR-02). ``dataset`` is the dataset's name/id, matching the PRD's
    example YAML field of the same name — not a nested Dataset, since a
    policy file is authored independently of, and validated against,
    whatever Dataset registration already exists.

    ``version`` defaults to "unversioned" rather than being required: real
    policy versioning is a Milestone 2 concern (a policy registry assigning
    versions on save), not something a human is expected to hand-write in a
    YAML file today. The field exists now because ValidationRun already
    carries a ``policy_version`` — this is the placeholder that keeps that
    shape stable until Milestone 2 gives it a real source.
    """

    model_config = ConfigDict(frozen=True)

    dataset: str = Field(min_length=1)
    version: str = "unversioned"
    rules: tuple[RuleConfig, ...] = Field(min_length=1)
