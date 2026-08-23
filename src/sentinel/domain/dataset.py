"""The Dataset: a registered data asset (FR-01).

Dataset is a pydantic model rather than a dataclass, even though it lives in
the domain package alongside the run-time fact objects. The distinction this
codebase draws isn't "pydantic vs. dataclass" — it's "does this object sit at
an external-input boundary." Dataset registration fields (name, owner,
criticality, ...) are typed in by a human and can be wrong in ways pydantic
is built to catch; a Metric or QualityEvent is produced by code, from data
already inside the system, with nothing left to validate.

Dataset is frozen for the same reason every other domain object is: it's a
snapshot of what was registered, not a mutable record you update in place.
A change to a dataset's registration is a new Dataset, not a mutation of the
old one — that question is deferred to whatever Milestone 2's persistence
layer decides "versioning a dataset" means; the domain object itself takes
no position on it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Criticality(StrEnum):
    """How much a dataset's failure matters operationally.

    Deliberately a separate type from Severity (see domain/events.py), even
    though the vocabulary overlaps. Criticality is a property of the
    dataset, set once at registration; Severity is a property of a rule,
    read from the policy on every evaluation. Conflating them would make it
    impossible to say "a HIGH severity rule on a LOW criticality dataset" —
    exactly the kind of context Milestone 5's incident prioritization is
    supposed to combine.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Dataset(BaseModel):
    """A registered data asset, per FR-01.

    ``source_type`` and ``environment`` are left as plain strings rather than
    enums on purpose: the set of supported data sources is still one adapter
    (Milestone 3 adds a second), and environment names are organization-
    specific. Constraining either now would be encoding a decision the
    project hasn't earned yet — widen this later if a real need appears.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    criticality: Criticality
    config_reference: str | None = None
