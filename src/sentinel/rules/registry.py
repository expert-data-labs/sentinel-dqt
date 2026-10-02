"""Maps a rule_type string to its Rule class.

Adding a rule means adding a file with ``@register_rule``; the orchestrator
doesn't change.
"""

from __future__ import annotations

from sentinel.rules.base import Rule

_REGISTRY: dict[str, type[Rule]] = {}


class RuleNotRegisteredError(Exception):
    """No Rule is registered for a given rule_type."""


def register_rule(cls: type[Rule]) -> type[Rule]:
    """Class decorator: register ``cls`` under its ``rule_type``. Rejects
    duplicates.
    """
    rule_type = cls.rule_type
    if rule_type in _REGISTRY:
        existing = _REGISTRY[rule_type].__name__
        raise ValueError(
            f"Rule type {rule_type!r} is already registered to {existing}; "
            f"cannot also register {cls.__name__}"
        )
    _REGISTRY[rule_type] = cls
    return cls


def get_rule(rule_type: str) -> Rule:
    """Return a new instance of the Rule for ``rule_type``, or raise
    RuleNotRegisteredError.
    """
    try:
        rule_cls = _REGISTRY[rule_type]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise RuleNotRegisteredError(
            f"No rule registered for type {rule_type!r}. Known types: {known}"
        ) from None
    return rule_cls()
