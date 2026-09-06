"""Reads a policy YAML file and returns a validated Policy.

Wraps both failure modes a policy file can hit — invalid YAML syntax, and
YAML that parses fine but fails the Policy schema — into one exception
type. A caller (the CLI, Milestone 2) should be able to catch one thing
and show the person who wrote the policy a clear reason it didn't load,
without needing to know whether the failure came from PyYAML or pydantic
underneath.

Milestone 2: now a thin wrapper over sentinel.config_loading.load_yaml_model
— the parse-and-wrap logic itself moved there once
sentinel.dataset_loader needed the identical logic for a second model
type. This module's own observable behavior (what it raises, and when)
is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from sentinel.config_loading import load_yaml_model
from sentinel.domain.policy import Policy


class PolicyLoadError(Exception):
    """A policy file could not be read, parsed, or validated."""


def load_policy(path: str | Path) -> Policy:
    return load_yaml_model(path, Policy, PolicyLoadError)
