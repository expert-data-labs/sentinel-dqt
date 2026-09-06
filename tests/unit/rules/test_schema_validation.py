from __future__ import annotations

import json

import pytest

from sentinel.domain import RuleConfig
from sentinel.rules.base import RuleConfigError
from sentinel.rules.schema_validation import SchemaValidationRule
from tests.unit.doubles import FakeDataSource


def _rule_config(expected_schema: dict[str, str] | None) -> RuleConfig:
    data: dict[str, object] = {
        "name": "orders_schema",
        "type": "schema",
        "threshold": {"strategy": "static", "max": 0},
    }
    if expected_schema is not None:
        data["expected_schema"] = expected_schema
    return RuleConfig.model_validate(data)


def _source_with_columns(**columns: object) -> FakeDataSource:
    """One row whose values FakeDataSource.columns() infers types from."""
    return FakeDataSource(rows=[dict(columns)])


def test_exact_match_reports_zero_differences() -> None:
    source = _source_with_columns(order_id="A1", amount=9.99)
    config = _rule_config({"order_id": "string", "amount": "float"})
    metric = SchemaValidationRule().compute(source, config)
    assert metric.value == 0.0
    details = json.loads(metric.details or "{}")
    assert details == {"missing_columns": [], "unexpected_columns": [], "type_mismatches": {}}


def test_missing_column_is_counted_and_named() -> None:
    source = _source_with_columns(order_id="A1")
    config = _rule_config({"order_id": "string", "created_at": "timestamp"})
    metric = SchemaValidationRule().compute(source, config)
    assert metric.value == 1.0
    details = json.loads(metric.details or "{}")
    assert details["missing_columns"] == ["created_at"]


def test_unexpected_column_is_counted_and_named() -> None:
    source = _source_with_columns(order_id="A1", extra_field=True)
    config = _rule_config({"order_id": "string"})
    metric = SchemaValidationRule().compute(source, config)
    assert metric.value == 1.0
    details = json.loads(metric.details or "{}")
    assert details["unexpected_columns"] == ["extra_field"]


def test_type_mismatch_is_counted_with_expected_and_actual() -> None:
    source = _source_with_columns(amount="9.99")  # inferred as string, not float
    config = _rule_config({"amount": "float"})
    metric = SchemaValidationRule().compute(source, config)
    assert metric.value == 1.0
    details = json.loads(metric.details or "{}")
    assert details["type_mismatches"] == {"amount": {"expected": "float", "actual": "string"}}


def test_multiple_differences_all_get_counted_and_reported() -> None:
    source = _source_with_columns(order_id="A1", extra_field=True)
    config = _rule_config({"order_id": "integer", "created_at": "timestamp"})
    metric = SchemaValidationRule().compute(source, config)
    # order_id type mismatch (string vs integer) + created_at missing + extra_field unexpected
    assert metric.value == 3.0
    details = json.loads(metric.details or "{}")
    assert details["missing_columns"] == ["created_at"]
    assert details["unexpected_columns"] == ["extra_field"]
    assert details["type_mismatches"] == {"order_id": {"expected": "integer", "actual": "string"}}


def test_no_actual_columns_reports_every_expected_column_as_missing() -> None:
    """An actual schema with no columns (an empty source.columns() mapping)
    is a degenerate but valid input to this rule's diff logic -- every
    expected column is, correctly, missing. See DataSource.columns() and
    FakeDataSource.columns() for how this can arise from an empty dataset;
    the corresponding real-adapter behavior (columns() staying populated
    even with zero rows) is covered in test_duckdb_source.py."""
    source = FakeDataSource(rows=[])
    config = _rule_config({"order_id": "string"})
    metric = SchemaValidationRule().compute(source, config)
    assert metric.value == 1.0
    details = json.loads(metric.details or "{}")
    assert details["missing_columns"] == ["order_id"]


def test_missing_expected_schema_raises_rule_config_error() -> None:
    source = _source_with_columns(order_id="A1")
    with pytest.raises(RuleConfigError, match="expected_schema"):
        SchemaValidationRule().compute(source, _rule_config(expected_schema=None))
