"""Maps a source_type string to its DataSource class.

Unlike rules and strategies, a DataSource is constructed with the dataset's
``config_reference``.
"""

from __future__ import annotations

from sentinel.datasources.base import DataSource

_REGISTRY: dict[str, type[DataSource]] = {}


class DataSourceNotRegisteredError(Exception):
    """No DataSource is registered for a given source_type."""


def register_data_source(cls: type[DataSource]) -> type[DataSource]:
    """Class decorator: register ``cls`` under its ``source_type``. Rejects
    duplicates.
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
    """Create the DataSource for ``source_type`` with ``config_reference``.

    Raises DataSourceNotRegisteredError for an unknown type.
    """
    try:
        source_cls = _REGISTRY[source_type]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise DataSourceNotRegisteredError(
            f"No data source registered for type {source_type!r}. Known types: {known}"
        ) from None
    return source_cls(config_reference)  # type: ignore[call-arg]
