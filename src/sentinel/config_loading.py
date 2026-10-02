"""Loads a YAML file into a validated pydantic model."""

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

    Every failure (unreadable file, bad YAML, non-mapping top level, schema
    error) is raised as ``error_cls`` so callers catch one exception type.
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
