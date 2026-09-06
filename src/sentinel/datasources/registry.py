"""A dict-based registry mapping a source_type string (a Dataset's
``source_type`` field) to the DataSource implementation that handles it.

Mirrors sentinel.rules.registry and sentinel.thresholds.registry: a new
DataSource adapter registers itself with ``@register_data_source`` and
callers never need a branch to pick one. This didn't exist before
Milestone 2 because no concrete DataSource implementation did either (see
Milestone 0's own notes on this); with DuckDBSource landing now and a
second adapter confirmed for Milestone 3, resolving by source_type is
worth the same one dict + one decorator every other registry uses.

One asymmetry from the other two registries: Rule and ThresholdStrategy
implementations are instantiated with no arguments (``rule_cls()``) — a
DataSource needs to know *which* dataset it's reading, so
``get_data_source`` takes a ``config_reference`` and passes it through to
the concrete class's constructor. Every registered DataSource is expected
to accept exactly that one argument.
"""

from __future__ import annotations

from sentinel.datasources.base import DataSource

_REGISTRY: dict[str, type[DataSource]] = {}


class DataSourceNotRegisteredError(Exception):
    """No DataSource is registered for a given source_type."""


def register_data_source(cls: type[DataSource]) -> type[DataSource]:
    """Class decorator: registers ``cls`` under its own ``source_type``.

    Reads the key from the class itself, rather than taking it as a
    decorator argument — the same reasoning as register_rule/
    register_threshold_strategy: exactly one place a source_type's name is
    spelled.
    """
    source_type = cls.source_type
    if source_type in _REGISTRY:
        existing = _REGISTRY[source_type].__name__
        raise ValueError(
            f"Source type {source_type!r} is already registered to {existing}; "
            f"cannot also register {cls.__name__}"
        )
    _REGISTRY[source_type] = cls
    return cls


def get_data_source(source_type: str, config_reference: str | None) -> DataSource:
    """Resolve and instantiate the DataSource registered for
    ``source_type``, passing it ``config_reference`` (from the Dataset
    being validated).

    Raises DataSourceNotRegisteredError, not a bare KeyError, so a caller
    several layers up (the CLI) can show a person "dataset declares source
    type X, which isn't implemented" instead of an unexplained lookup
    failure.
    """
    try:
        source_cls = _REGISTRY[source_type]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise DataSourceNotRegisteredError(
            f"No data source registered for type {source_type!r}. Known types: {known}"
        ) from None
    return source_cls(config_reference)  # type: ignore[call-arg]
