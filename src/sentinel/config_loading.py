"""Shared machinery for loading a validated pydantic model from a YAML
config file, with every failure mode wrapped into one caller-supplied
exception type.

Factored out once a second caller needed it (Milestone 2's dataset
loader, below) rather than upfront — Milestone 1's policy_loader had this
exact parse-and-wrap logic inline, and duplicating it for a second model
type is what finally justified extracting it. sentinel.policy_loader.loader
now builds on this too; its own observable behavior (what it raises, and
when) is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

_ModelT = TypeVar("_ModelT", bound=BaseModel)


def load_yaml_model(
    path: str | Path, model_cls: type[_ModelT], error_cls: type[Exception]
) -> _ModelT:
    """Read ``path`` as YAML and validate it against ``model_cls``.

    Wraps every failure mode — an unreadable file, invalid YAML syntax, a
    non-mapping top level, or a schema validation failure — into a single
    ``error_cls(message)`` instance, so a caller can catch exactly one
    exception type regardless of which stage failed.
    """
    path = Path(path)

    try:
        text = path.read_text()
    except OSError as exc:
        raise error_cls(f"{path}: could not be read ({exc})") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise error_cls(f"{path}: not valid YAML: {exc}") from exc

    if raw is None:
        raise error_cls(f"{path}: file is empty")
    if not isinstance(raw, dict):
        raise error_cls(
            f"{path}: expected a mapping at the top level, got {type(raw).__name__}"
        )

    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise error_cls(f"{path}: failed validation:\n{exc}") from exc
