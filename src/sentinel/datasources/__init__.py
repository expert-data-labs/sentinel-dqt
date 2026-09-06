"""Data source adapters: capability-based access to whatever backs a dataset.

Rules call named capabilities (row_count, null_count, ...) rather than
executing engine-specific queries, so rule semantics don't change when the
adapter does (FR-10).
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
