"""Smoke test for Task 1 (repo scaffolding): the package installs and imports
cleanly, and every module boundary from the architecture doc exists.

This is intentionally the only test until Task 2 introduces real domain
objects to assert against — its job is to prove the scaffolding, not the
(nonexistent yet) behavior.
"""

import importlib


def test_sentinel_package_imports() -> None:
    assert importlib.import_module("sentinel") is not None


def test_all_declared_subpackages_import() -> None:
    subpackages = [
        "sentinel.domain",
        "sentinel.rules",
        "sentinel.thresholds",
        "sentinel.datasources",
        "sentinel.policy_loader",
        "sentinel.orchestration",
        "sentinel.cli",
    ]
    for name in subpackages:
        assert importlib.import_module(name) is not None
