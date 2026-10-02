"""The current time, as Sentinel sees it.

Rules and the orchestrator call ``clock.now()`` instead of ``datetime.now()``.
It returns the real UTC time unless a block pins it:

    with clock.frozen_at(datetime(2026, 9, 1, 6, tzinfo=UTC)):
        orchestrator.run(...)   # metrics are stamped 2026-09-01 06:00

Used to replay or backfill past days. The override is a context variable, so
pinning the time in one thread or request never affects another.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_frozen: ContextVar[datetime | None] = ContextVar("sentinel_frozen_now", default=None)


def now() -> datetime:
    """The current UTC time, or the pinned time inside ``frozen_at``."""
    pinned = _frozen.get()
    return pinned if pinned is not None else datetime.now(UTC)


@contextmanager
def frozen_at(moment: datetime) -> Iterator[None]:
    """Pin ``now()`` to ``moment`` (must be timezone-aware) for the block."""
    if moment.tzinfo is None:
        raise ValueError("frozen_at needs a timezone-aware datetime")
    token = _frozen.set(moment.astimezone(UTC))
    try:
        yield
    finally:
        _frozen.reset(token)
