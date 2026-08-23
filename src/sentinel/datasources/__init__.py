"""Data source adapters: capability-based access to whatever backs a dataset.

Rules call named capabilities (row_count, null_count, ...) rather than
executing engine-specific queries, so rule semantics don't change when the
adapter does (FR-10).
"""

from sentinel.datasources.base import DataSource

__all__ = ["DataSource"]
