"""Loads and validates declarative quality policies from configuration files."""

from sentinel.policy_loader.loader import PolicyLoadError, load_policy

__all__ = ["PolicyLoadError", "load_policy"]
