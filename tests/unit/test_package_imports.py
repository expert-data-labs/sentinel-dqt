"""Smoke test: the package imports and its main modules exist."""

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
