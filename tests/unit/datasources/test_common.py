from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentinel.datasources._common import (
    ConfigReferenceError,
    MissingDriverError,
    as_utc,
    expand_env,
    import_driver,
    pop_url_param,
    url_params,
)


def test_expand_env_substitutes_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_USER", "alice")
    monkeypatch.setenv("DB_PASSWORD", "s3cret")
    assert (
        expand_env("postgresql://${DB_USER}:${DB_PASSWORD}@host/db")
        == "postgresql://alice:s3cret@host/db"
    )


def test_expand_env_names_every_unset_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_A", raising=False)
    monkeypatch.delenv("MISSING_B", raising=False)
    with pytest.raises(ConfigReferenceError, match="MISSING_A, MISSING_B"):
        expand_env("x://${MISSING_B}:${MISSING_A}@h")


def test_expand_env_leaves_text_without_references_alone() -> None:
    assert expand_env("data/orders.csv") == "data/orders.csv"


def test_pop_url_param_removes_only_that_parameter() -> None:
    url, table = pop_url_param("pg://h/db?table=orders&sslmode=require", "table", example="e")
    assert table == "orders"
    assert url == "pg://h/db?sslmode=require"


def test_pop_url_param_requires_the_parameter() -> None:
    with pytest.raises(ConfigReferenceError, match="'table'"):
        pop_url_param("pg://h/db", "table", example="pg://h/db?table=t")


def test_url_params_flattens_the_query() -> None:
    assert url_params("x://h/p?a=1&b=2") == {"a": "1", "b": "2"}


def test_as_utc_handles_naive_aware_and_other_values() -> None:
    naive = datetime(2026, 1, 1, 10, 0)
    ist = datetime(2026, 1, 1, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert as_utc(naive) == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert as_utc(ist) == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert as_utc(ist).tzinfo is UTC
    assert as_utc(42) == 42


def test_import_driver_explains_which_extra_to_install() -> None:
    with pytest.raises(MissingDriverError, match=r"sentinel\[warehouse\]"):
        import_driver("no_such_driver_module", "warehouse")
