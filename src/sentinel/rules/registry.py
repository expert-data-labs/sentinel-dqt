"""A dict-based registry mapping a rule_type string (a RuleConfig's ``type``
field, from a policy YAML) to the Rule implementation that handles it.

This is the mechanism that makes "add a rule = add a file" true: a new Rule
registers itself with ``@register_rule`` and the orchestrator never needs
to change to know about it. It's deliberately a plain dict behind two
functions, not a plugin framework — there's nothing here that needs to be
swapped out or mocked as its own abstraction.
"""

from __future__ import annotations

from sentinel.rules.base import Rule

_REGISTRY: dict[str, type[Rule]] = {}


class RuleNotRegisteredError(Exception):
    """No Rule is registered for a given rule_type."""


def register_rule(cls: type[Rule]) -> type[Rule]:
    """Class decorator: registers ``cls`` under its own ``rule_type``.

    Reads the key from the class itself, rather than taking it as a
    decorator argument, so there is exactly one place a rule's type name is
    spelled — no way for a decorator argument and the class's own
    ``rule_type`` to silently disagree.
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
    """Resolve and instantiate the Rule registered for ``rule_type``.

    Raises RuleNotRegisteredError, not a bare KeyError, so a caller several
    layers up (the orchestrator, eventually the CLI) can show a person
    "policy references rule type X, which isn't implemented" instead of an
    unexplained lookup failure.
    """
    try:
        rule_cls = _REGISTRY[rule_type]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise RuleNotRegisteredError(
            f"No rule registered for type {rule_type!r}. Known types: {known}"
        ) from None
    return rule_cls()
