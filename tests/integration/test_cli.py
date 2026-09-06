"""Integration tests for `sentinel validate` and `sentinel history` — the
real CLI, invoked through Typer's CliRunner, against the real orders/
configuration this milestone shipped at the repo root (datasets/orders.yaml,
policies/orders.yaml, data/orders.csv — Part 8 of the Milestone 2 ADR) and a
throwaway temp-file DuckDB history store, never the project's own
sentinel.duckdb.

This is the one place bootstrap, resolution, DuckDBSource, the
orchestrator, persistence, and both commands' printed output are all
exercised together, wired exactly as `sentinel validate orders` runs for
an actual user from the repo root. Unlike
tests/integration/test_end_to_end.py (Milestone 1, against
FakeDataSource and the loader functions called directly), this is
Milestone 2's own top-to-bottom acceptance test.

Every rule in policies/orders.yaml fails against data/orders.csv's 12-row
sample (see test_end_to_end.py's own docstring for why that's a feature,
not a bug, of this fixture), and none of them override the RuleConfig
default of blocking=True — so every `validate` call in this module is
expected to exit 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sentinel.cli.main import app

REPO_ROOT = Path(__file__).parents[2]

runner = CliRunner()


@pytest.fixture(autouse=True)
def _real_repo_config_and_temp_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Resolve datasets/policies from the repo's own default directories
    (no SENTINEL_DATASETS_DIR/SENTINEL_POLICIES_DIR override) by running
    from the repo root, but redirect SENTINEL_DB_PATH to a fresh temp
    file per test so these tests never touch the real sentinel.duckdb."""
    monkeypatch.delenv("SENTINEL_DATASETS_DIR", raising=False)
    monkeypatch.delenv("SENTINEL_POLICIES_DIR", raising=False)
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "history.duckdb"))
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
