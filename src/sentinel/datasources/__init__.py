"""Data source adapters.

Rules call capabilities (row_count, null_count, ...) instead of writing engine-
specific SQL, so a rule behaves the same on every backend.
"""

from sentinel.datasources.base import DataSource
from sentinel.datasources.registry import (
    DataSourceNotRegisteredError,
    get_data_source,
    register_data_source,
)

__all__ = [
    "DataSource",
    "DataSourceNotRegisteredError",
    "get_data_source",
    "register_data_source",
]
