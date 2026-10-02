"""DataSource interface.

Each method answers one question a rule needs ("how many rows?"). There is no
generic "run this query" method, so SQL dialects never leak into rules.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol


class DataSource(Protocol):
    """Read-only access to one dataset's measurable properties.

    ``source_type`` is the Dataset's ``source_type`` value and the registry key.
    Empty-dataset behavior is defined per method so every adapter matches.
    """

    source_type: ClassVar[str]

    def row_count(self) -> int:
        """Total number of rows. 0 for an empty dataset; never negative."""
        ...

    def null_count(self, column: str) -> int:
        """Rows where ``column`` is null. 0 for an empty dataset."""
        ...

    def distinct_count(self, column: str) -> int:
        """Distinct non-null values in ``column`` (like SQL ``COUNT(DISTINCT)``).

        0 for an empty dataset or an all-null column.
        """
        ...

    def max_value(self, column: str) -> Any:
        """Largest non-null value in ``column``, or None if there is none.

        Timestamps are returned as timezone-aware UTC. Naive values are assumed
        to be UTC.
        """
        ...

    def columns(self) -> dict[str, str]:
        """Column names mapped to Sentinel's canonical types.

        Types: string, integer, float, decimal, boolean, timestamp, date,
        unknown. Works the same on an empty dataset.
        """
        ...
