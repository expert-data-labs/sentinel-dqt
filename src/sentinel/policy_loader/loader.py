"""Reads a policy YAML file and returns a validated Policy.

Wraps both failure modes a policy file can hit — invalid YAML syntax, and
YAML that parses fine but fails the Policy schema — into one exception
type. A caller (the CLI in Milestone 2, the orchestrator before that)
should be able to catch one thing and show the person who wrote the policy
a clear reason it didn't load, without needing to know whether the failure
came from PyYAML or pydantic underneath.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from sentinel.domain.policy import Policy


class PolicyLoadError(Exception):
    """A policy file could not be read, parsed, or validated."""


def load_policy(path: str | Path) -> Policy:
    path = Path(path)

    try:
        text = path.read_text()
    except OSError as exc:
        raise PolicyLoadError(f"{path}: could not be read ({exc})") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PolicyLoadError(f"{path}: not valid YAML: {exc}") from exc

    if raw is None:
        raise PolicyLoadError(f"{path}: file is empty")
    if not isinstance(raw, dict):
        raise PolicyLoadError(
            f"{path}: expected a mapping at the top level, got {type(raw).__name__}"
        )

    try:
        return Policy.model_validate(raw)
    except ValidationError as exc:
        raise PolicyLoadError(f"{path}: policy failed validation:\n{exc}") from exc
