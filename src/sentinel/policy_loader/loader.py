"""Reads a policy YAML file into a validated Policy.

All failures (unreadable file, bad YAML, schema error) raise PolicyLoadError.
"""

from __future__ import annotations

from pathlib import Path

from sentinel.config_loading import load_yaml_model
from sentinel.domain.policy import Policy


class PolicyLoadError(Exception):
    """A policy file could not be read, parsed, or validated."""


def load_policy(path: str | Path) -> Policy:
    return load_yaml_model(path, Policy, PolicyLoadError)
