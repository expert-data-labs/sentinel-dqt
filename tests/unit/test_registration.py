"""Tests for sentinel.registration.register_all().

Deliberately does not use an isolated-registry fixture (contrast with
tests/unit/rules/test_registry.py, tests/unit/thresholds/test_registry.py,
and tests/unit/datasources/test_registry.py): register_all()'s imports are
cached by Python after the first time any test module imports
sentinel.rules.row_count/null_rate/uniqueness, sentinel.thresholds.static,
or sentinel.datasources.duckdb_source directly (which the per-component
unit tests do, on purpose, to test them in isolation from the registry).
That means these real registrations are already process-global and
permanent by the time any test runs, regardless of whether register_all()
has been called yet in this file — so there is no meaningful "before
register_all(), nothing is registered" state to assert within a shared
pytest session. What *is* reliably true regardless of import order is
asserted below instead: that register_all() covers every Milestone 1/2/4
type, and that calling it more than once is safe.
"""

from __future__ import annotations

from sentinel.datasources import get_data_source
from sentinel.registration import register_all
from sentinel.rules import get_rule
from sentinel.thresholds import get_threshold_strategy


def test_register_all_makes_every_milestone_1_rule_resolvable() -> None:
    register_all()

    assert get_rule("row_count").rule_type == "row_count"
    assert get_rule("null_rate").rule_type == "null_rate"
    assert get_rule("uniqueness").rule_type == "uniqueness"


def test_register_all_makes_the_static_strategy_resolvable() -> None:
    register_all()

    assert get_threshold_strategy("static").strategy_type == "static"


def test_register_all_makes_every_milestone_4_strategy_resolvable() -> None:
    register_all()

    assert get_threshold_strategy("percentage_deviation").strategy_type == "percentage_deviation"
    assert get_threshold_strategy("statistical").strategy_type == "statistical"
    assert get_threshold_strategy("median_mad").strategy_type == "median_mad"
    assert get_threshold_strategy("seasonal").strategy_type == "seasonal"


def test_register_all_makes_the_duckdb_source_resolvable() -> None:
    register_all()

    source = get_data_source("duckdb", "unused/path.csv")
    assert source.source_type == "duckdb"


def test_register_all_is_safe_to_call_more_than_once() -> None:
    register_all()
    register_all()  # must not raise a duplicate-registration error

    assert get_rule("row_count").rule_type == "row_count"
    assert get_threshold_strategy("static").strategy_type == "static"
    assert get_data_source("duckdb", "unused/path.csv").source_type == "duckdb"
