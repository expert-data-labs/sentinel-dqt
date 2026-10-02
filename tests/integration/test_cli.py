"""End-to-end CLI tests for ``sentinel validate`` and ``sentinel history``.

Uses the repo's real orders config (datasets/, policies/, data/orders.csv) and
the Postgres test store. Every orders rule fails on the 12-row sample and is
blocking, so ``validate`` always exits 2 here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sentinel.cli import bootstrap
from sentinel.cli.main import app
from sentinel.persistence import migrate
from sentinel.persistence.engine import StoreConnection

REPO_ROOT = Path(__file__).parents[2]

runner = CliRunner()


@pytest.fixture(autouse=True)
def _real_repo_config_and_test_store(
    monkeypatch: pytest.MonkeyPatch, store: StoreConnection
) -> None:
    """Run from the repo root against the (emptied) test store."""
    monkeypatch.delenv("SENTINEL_DATASETS_DIR", raising=False)
    monkeypatch.delenv("SENTINEL_POLICIES_DIR", raising=False)
    monkeypatch.chdir(REPO_ROOT)


def test_validate_prints_a_summary_and_exits_2_for_a_blocking_failure() -> None:
    result = runner.invoke(app, ["validate", "orders"])

    assert result.exit_code == 2
    assert "Dataset: orders" in result.output
    assert "Result:  FAIL (blocking)" in result.output
    assert "row_count" in result.output
    assert "✗" in result.output


def test_history_reads_back_the_run_validate_just_wrote() -> None:
    assert runner.invoke(app, ["validate", "orders"]).exit_code == 2

    result = runner.invoke(app, ["history", "orders"])

    assert result.exit_code == 0
    assert "Dataset: orders" in result.output
    assert "FAIL" in result.output
    assert "row_count" in result.output  # a failed rule name in the history line


def test_history_reports_no_runs_for_a_dataset_never_validated() -> None:
    result = runner.invoke(app, ["history", "orders"])

    assert result.exit_code == 0
    assert "No recorded runs" in result.output


def test_history_limit_option_caps_how_many_runs_are_shown() -> None:
    for _ in range(3):
        assert runner.invoke(app, ["validate", "orders"]).exit_code == 2

    result = runner.invoke(app, ["history", "orders", "--limit", "1"])

    assert result.exit_code == 0
    assert result.output.count("run=") == 1


def test_validate_exits_3_when_the_store_is_not_migrated(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch where bootstrap looks it up (it imports the name directly).
    monkeypatch.setattr(bootstrap, "head_revision", lambda: "9999")

    result = runner.invoke(app, ["validate", "orders"])

    assert result.exit_code == 3
    assert "sentinel db upgrade" in result.output


def test_db_current_reports_the_store_at_head() -> None:
    result = runner.invoke(app, ["db", "current"])

    assert result.exit_code == 0
    head = migrate.head_revision()
    assert f"current: {head}  head: {head}" in result.output
