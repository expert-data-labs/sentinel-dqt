"""Policy config: what a user declares in a policy YAML file.

ThresholdConfig keeps a ``strategy`` name plus an open ``params`` dict, so a new
strategy doesn't change this schema; each strategy validates its own params.
RuleConfig uses dedicated optional fields (``column``, ``expected_schema``)
because they have different shapes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel.domain.events import Severity


class ThresholdConfig(BaseModel):
    """Threshold settings for one rule.

    Accepts the flat YAML form ``{strategy: static, min: 1000}`` and moves every
    key except ``strategy`` into ``params``.
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
    """One rule declared in a Policy.

    The YAML key ``type`` maps to ``rule_type`` (avoids shadowing the builtin).
    ``expected_schema`` is used by the schema validation rule; the rule itself
    validates its values.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str = Field(min_length=1)
    rule_type: str = Field(min_length=1, alias="type")
    column: str | None = None
    expected_schema: dict[str, str] | None = None
    severity: Severity = Severity.WARNING
    blocking: bool = True
    threshold: ThresholdConfig


class Policy(BaseModel):
    """A set of quality rules for one dataset.

    ``dataset`` is the dataset's name/id. ``version`` defaults to "unversioned"
    until policy versioning exists.
    """

    model_config = ConfigDict(frozen=True)

    dataset: str = Field(min_length=1)
    version: str = "unversioned"
    rules: tuple[RuleConfig, ...] = Field(min_length=1)
