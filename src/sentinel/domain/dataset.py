"""Dataset: a registered data asset.

A pydantic model because its fields are user input and need validation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Criticality(StrEnum):
    """How much a dataset's failure matters.

    Separate from Severity: criticality belongs to the dataset, severity to a
    rule. Prioritization combines the two.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Dataset(BaseModel):
    """A registered data asset.

    ``source_type`` and ``environment`` are plain strings so new adapters and
    environments don't need a schema change.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    criticality: Criticality
    config_reference: str | None = None
