"""A dict-based registry mapping a strategy_type string (a ThresholdConfig's
``strategy`` field) to the ThresholdStrategy implementation that handles it.

Mirrors sentinel.rules.registry exactly, for the same reason: a new
ThresholdStrategy registers itself with ``@register_threshold_strategy``
and the orchestrator never needs to change to know about it.
"""

from __future__ import annotations

from sentinel.thresholds.base import ThresholdStrategy

_REGISTRY: dict[str, type[ThresholdStrategy]] = {}


class ThresholdStrategyNotRegisteredError(Exception):
    """No ThresholdStrategy is registered for a given strategy_type."""


def register_threshold_strategy(cls: type[ThresholdStrategy]) -> type[ThresholdStrategy]:
    """Class decorator: registers ``cls`` under its own ``strategy_type``.

    Reads the key from the class itself, rather than taking it as a
    decorator argument — the same reasoning as register_rule: exactly one
    place a strategy's type name is spelled.
    """
    strategy_type = cls.strategy_type
    if strategy_type in _REGISTRY:
        existing = _REGISTRY[strategy_type].__name__
        raise ValueError(
            f"Strategy type {strategy_type!r} is already registered to {existing}; "
            f"cannot also register {cls.__name__}"
        )
    _REGISTRY[strategy_type] = cls
    return cls


def get_threshold_strategy(strategy_type: str) -> ThresholdStrategy:
    """Resolve and instantiate the ThresholdStrategy registered for
    ``strategy_type``.

    Raises ThresholdStrategyNotRegisteredError, not a bare KeyError, so a
    caller can show a person "policy references threshold strategy X, which
    isn't implemented" instead of an unexplained lookup failure.
    """
    try:
        strategy_cls = _REGISTRY[strategy_type]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise ThresholdStrategyNotRegisteredError(
            f"No threshold strategy registered for type {strategy_type!r}. Known types: {known}"
        ) from None
    return strategy_cls()
