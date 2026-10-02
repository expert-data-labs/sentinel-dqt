"""Pins the outcomes the example datasets promise in docs/examples.md.

If an example's data, policy or a strategy changes so that the walkthrough
would no longer be true, one of these fails.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from examples.setup import (
    load_events_table,
    load_reviews_collection,
    load_shipments_table,
    seed_signups_history,
    write_clickstream_parquet,
)
from typer.testing import CliRunner

from sentinel.cli.main import app
from sentinel.dataset_loader import load_dataset
from sentinel.datasources import get_data_source
from sentinel.domain import Status
from sentinel.persistence.engine import StoreConnection
from sentinel.policy_loader import load_policy
from sentinel.registration import register_all
from sentinel.validation_service import validate_and_record

REPO_ROOT = Path(__file__).parents[2]

runner = CliRunner()


@pytest.fixture(autouse=True)
def _repo_root(monkeypatch: pytest.MonkeyPatch, store: StoreConnection) -> None:
    monkeypatch.delenv("SENTINEL_DATASETS_DIR", raising=False)
    monkeypatch.delenv("SENTINEL_POLICIES_DIR", raising=False)
    monkeypatch.chdir(REPO_ROOT)


def test_customers_passes_every_rule() -> None:
    result = runner.invoke(app, ["validate", "customers"])

    assert result.exit_code == 0, result.output
    assert "Result:  PASS" in result.output
    assert "✗" not in result.output


def test_products_records_a_non_blocking_failure_and_still_exits_0() -> None:
    result = runner.invoke(app, ["validate", "products"])

    assert result.exit_code == 0, result.output
    assert "✗ description_not_null" in result.output
    assert "priority=" in result.output  # an incident was still recorded
    assert result.output.count("✗") == 1


def test_signups_compares_the_adaptive_strategies(store: StoreConnection) -> None:
    seed_signups_history(store)

    result = runner.invoke(app, ["validate", "signups"])

    assert result.exit_code == 0, result.output  # every adaptive rule is non-blocking
    assert "✓ row_count_sanity" in result.output
    assert "✗ row_count_vs_recent_mean" in result.output  # baseline mixes in weekends
    assert "✓ row_count_statistical" in result.output  # band is very wide
    assert "✓ row_count_median_mad" in result.output  # locks onto the weekday level
    if datetime.now(UTC).weekday() < 5:
        assert "✓ row_count_seasonal" in result.output  # 1000 is normal for a weekday
    else:
        assert "✗ row_count_seasonal" in result.output  # 1000 is far above a weekend


def test_events_on_postgres_passes_every_rule(store: StoreConnection) -> None:
    server = os.environ.get(
        "SENTINEL_TEST_POSTGRES_DSN", "postgresql://sentinel:sentinel@localhost:5432/sentinel"
    )
    url = urlunsplit(urlsplit(server)._replace(path="/sentinel_examples_test"))
    load_events_table(url)

    register_all()
    dataset = load_dataset(REPO_ROOT / "datasets" / "events.yaml")
    dataset = dataset.model_copy(update={"config_reference": f"{url}?table=events"})
    policy = load_policy(REPO_ROOT / "policies" / "events.yaml")
    source = get_data_source(dataset.source_type, dataset.config_reference)

    run, _ = validate_and_record(store, dataset, policy, source)

    failed = [e.rule_name for e in run.quality_events if e.status is not Status.PASS]
    assert failed == []


def _validate(name: str, store: StoreConnection, config_reference: str) -> dict[str, Status]:
    register_all()
    dataset = load_dataset(REPO_ROOT / "datasets" / f"{name}.yaml")
    dataset = dataset.model_copy(update={"config_reference": config_reference})
    policy = load_policy(REPO_ROOT / "policies" / f"{name}.yaml")
    source = get_data_source(dataset.source_type, dataset.config_reference)
    run, _ = validate_and_record(store, dataset, policy, source)
    return {e.rule_name: e.status for e in run.quality_events}


def _unavailable(backend: str, exc: Exception) -> None:
    if backend in os.environ.get("SENTINEL_REQUIRE_BACKENDS", ""):
        raise exc
    pytest.skip(f"{backend} unavailable: {type(exc).__name__}")


def test_clickstream_parquet_passes_every_rule(store: StoreConnection, tmp_path: Path) -> None:
    path = tmp_path / "clickstream.parquet"
    write_clickstream_parquet(path)

    statuses = _validate("clickstream", store, str(path))

    assert set(statuses.values()) == {Status.PASS}


def test_shipments_on_mysql_catches_the_double_shipped_orders(
    store: StoreConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYSQL_PASSWORD", "sentinel")
    try:
        load_shipments_table()
    except Exception as exc:  # noqa: BLE001
        _unavailable("mysql", exc)
    reference = load_dataset(REPO_ROOT / "datasets" / "shipments.yaml").config_reference
    assert reference is not None and "${MYSQL_PASSWORD}" in reference

    statuses = _validate("shipments", store, reference)

    assert statuses.pop("one_shipment_per_order") is Status.FAIL
    assert set(statuses.values()) == {Status.PASS}


def test_reviews_on_mongodb_treats_missing_fields_as_null(store: StoreConnection) -> None:
    url = "mongodb://localhost:27017/sentinel_examples_test"
    try:
        load_reviews_collection(url)
    except Exception as exc:  # noqa: BLE001
        _unavailable("mongodb", exc)

    statuses = _validate("reviews", store, f"{url}?collection=reviews")

    assert set(statuses.values()) == {Status.PASS}
