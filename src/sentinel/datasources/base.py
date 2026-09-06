"""The DataSource interface (FR-10): capability-based access to whatever
backs a dataset, so a Rule's semantics don't change when the adapter does.

Every method answers a specific question a Rule needs answered ("how many
rows", "how many nulls in this column") rather than exposing a generic
"run this query" escape hatch. A generic query interface would leak SQL
dialect into every Rule and defeat the entire point of this contract; the
cost is that this Protocol grows by one method whenever a genuinely new
kind of measurement is needed — Milestone 3's ``columns()`` (schema
introspection, for the Schema Validation rule) is exactly the growth this
docstring anticipated back at Milestone 0 — a visible, one-file cost, not
a silent leak.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol


class DataSource(Protocol):
    """Read-only access to one dataset's measurable properties.

    Implementations back this with whatever engine a Dataset's
    ``source_type`` points at (DuckDB, added in Milestone 2; PostgreSQL,
    added in Milestone 3); every method's behavior on an empty dataset or
    an all-null column is specified here so a Rule can rely on it being
    the same regardless of adapter.

    ``source_type`` is a ClassVar, added in Milestone 2 alongside
    ``sentinel.datasources.registry`` — it mirrors ``Rule.rule_type`` and
    ``ThresholdStrategy.strategy_type`` exactly: the string a Dataset's own
    ``source_type`` field names this adapter by, and the key the registry
    looks it up under. Test doubles satisfying this Protocol (see
    ``tests.unit.doubles.FakeDataSource``) need this attribute too, the
    same way ``DummyRule``/``DummyThresholdStrategy`` already carry theirs.
    """

    source_type: ClassVar[str]

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

        Returns ``None`` for an empty dataset or an all-null column, rather
        than raising — a caller that can't handle "no data yet" should
        check ``row_count()``/``null_count()`` first.

        **Timestamp contract (Milestone 3):** when ``column`` holds
        timestamps — the shape ``FreshnessRule`` (``sentinel.rules.freshness``)
        relies on for ``max(updated_at)`` vs. now — the returned value is a
        timezone-aware ``datetime`` in UTC. If the underlying store has no
        timezone on the value (a naive ``TIMESTAMP``, the common case for
        both a DuckDB CSV read and Postgres's ``timestamp without time
        zone``), the adapter attaches UTC rather than leaving it naive or
        assuming the process's local time. This is what lets a Rule do
        plain ``datetime.now(UTC) - source.max_value(column)`` arithmetic
        without knowing or caring which backend answered the query — every
        adapter converges on the same contract before the Rule ever sees
        the value.
        """
        ...

    def columns(self) -> dict[str, str]:
        """Every column's name mapped to a canonical Sentinel type name —
        not the backend's native type string. Backs ``SchemaValidationRule``
        (``sentinel.rules.schema_validation``, Milestone 3).

        The canonical vocabulary is deliberately small:
        ``string``, ``integer``, ``float``, ``decimal``, ``boolean``,
        ``timestamp``, ``date``, and ``unknown`` (the escape hatch for a
        native type an adapter doesn't recognize — reported as a type
        mismatch by the Rule, not a crash). Each adapter owns its own
        native-type -> canonical-type mapping internally; nothing about a
        specific backend's type system reaches this method's caller. See
        ``docs/architecture/0004-milestone-3-architecture.md`` Part 3a.

        Schema is structural, not data-dependent: this returns the same
        result for an empty dataset (0 rows) as for a populated one — a
        DuckDB ``DESCRIBE`` and Postgres's ``information_schema.columns``
        both answer from the file/table's declared shape regardless of row
        count, so ``SchemaValidationRule`` needs no empty-dataset special
        case.
        """
        ...
