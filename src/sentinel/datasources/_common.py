"""Helpers shared by the data-source adapters."""

from __future__ import annotations

import importlib
import os
import re
from datetime import UTC, datetime
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingDriverError(ImportError):
    """The adapter's database driver isn't installed."""


class ConfigReferenceError(ValueError):
    """A ``config_reference`` is malformed or refers to an unset environment variable."""


def import_driver(module: str, extra: str) -> ModuleType:
    """Import an optional driver, or explain which extra installs it."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingDriverError(
            f"The {extra!r} data source needs the {module!r} package. "
            f"Install it with: pip install 'sentinel[{extra}]'  (or: uv sync --extra {extra})"
        ) from exc


def expand_env(text: str) -> str:
    """Replace ``${NAME}`` with environment variable values, so secrets stay out of YAML.

    Raises ConfigReferenceError naming any variable that isn't set.
    """
    missing = [name for name in _ENV_REFERENCE.findall(text) if name not in os.environ]
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise ConfigReferenceError(f"config_reference uses unset environment variable(s): {names}")
    return _ENV_REFERENCE.sub(lambda m: os.environ[m.group(1)], text)


def as_utc(value: Any) -> Any:
    """Return datetimes as UTC (naive ones are assumed UTC); pass other values through."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value


def pop_url_param(url: str, param: str, *, example: str) -> tuple[str, str]:
    """Split ``url`` into (url without ``param``, value of ``param``).

    Raises ConfigReferenceError if ``param`` is missing; ``example`` shows the
    expected form in the message.
    """
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    values = query.pop(param, None)
    if not values or not values[0]:
        raise ConfigReferenceError(
            f"config_reference needs a {param!r} query parameter, e.g. {example!r}"
        )
    remaining = urlunsplit(parts._replace(query=urlencode(query, doseq=True)))
    return remaining, values[0]


def url_params(url: str) -> dict[str, str]:
    """Query parameters of ``url`` as a flat dict (last value wins)."""
    return {key: values[-1] for key, values in parse_qs(urlsplit(url).query).items()}
