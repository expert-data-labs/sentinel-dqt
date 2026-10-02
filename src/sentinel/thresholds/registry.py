"""Maps a strategy_type string to its ThresholdStrategy class."""

from __future__ import annotations

from sentinel.thresholds.base import ThresholdStrategy

_REGISTRY: dict[str, type[ThresholdStrategy]] = {}


class ThresholdStrategyNotRegisteredError(Exception):
    """No ThresholdStrategy is registered for a given strategy_type."""


def register_threshold_strategy(cls: type[ThresholdStrategy]) -> type[ThresholdStrategy]:
    """Class decorator: register ``cls`` under its ``strategy_type``. Rejects
    duplicates.
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
    """Return a new instance for ``strategy_type``, or raise
    ThresholdStrategyNotRegisteredError.
    """
    try:
        strategy_cls = _REGISTRY[strategy_type]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise ThresholdStrategyNotRegisteredError(
            f"No threshold strategy registered for type {strategy_type!r}. Known types: {known}"
        ) from None
    return strategy_cls()
