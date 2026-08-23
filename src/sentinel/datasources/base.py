"""The DataSource interface (FR-10): capability-based access to whatever
backs a dataset, so a Rule's semantics don't change when the adapter does.

Every method answers a specific question a Rule needs answered ("how many
rows", "how many nulls in this column") rather than exposing a generic
"run this query" escape hatch. A generic query interface would leak SQL
dialect into every Rule and defeat the entire point of this contract; the
cost is that this Protocol grows by one method whenever a genuinely new
kind of measurement is needed (schema introspection, when Milestone 3's
schema validation rule arrives) — a visible, one-file cost, not a silent
leak.
"""

from __future__ import annotations

from typing import Any, Protocol


class DataSource(Protocol):
    """Read-only access to one dataset's measurable properties.

    Implementations back this with whatever engine a Dataset's
    ``source_type`` points at (DuckDB for Milestone 1); every method's
    behavior on an empty dataset or an all-null column is specified here so
    a Rule can rely on it being the same regardless of adapter.
    """

    def row_count(self) -> int:
        """Total number of rows. 0 for an empty dataset; never negative."""
        ...

    def null_count(self, column: str) -> int:
        """Number of rows where ``column`` is null.

        0 for an empty dataset. Equal to ``row_count()`` if every value in
        the column is null.
        """
        ...

    def distinct_count(self, column: str) -> int:
        """Number of distinct non-null values in ``column`` — matches SQL's
        ``COUNT(DISTINCT column)``: nulls are excluded, not counted as one
        more distinct value.

        0 for an empty dataset, and 0 if every value in the column is null
        (not 1 — null isn't "a value" for this count).
        """
        ...

    def max_value(self, column: str) -> Any:
        """The largest non-null value in ``column``.

        Not used by any Milestone 0/1 rule — reserved for Milestone 3's
        freshness rule (``max(updated_at)`` vs. now). Kept in the interface
        now because it's part of the approved Milestone 0 contract; if
        Milestone 3 turns out to need a different shape (timezone handling,
        a null-safe default expressed differently), this signature should
        flex to fit that real need rather than the other way around.

        Returns ``None`` for an empty dataset or an all-null column, rather
        than raising — a caller that can't handle "no data yet" should
        check ``row_count()``/``null_count()`` first.
        """
        ...
