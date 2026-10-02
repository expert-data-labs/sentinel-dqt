"""Composition root: sets up what every CLI command needs."""

from __future__ import annotations

from dataclasses import dataclass

from sentinel.persistence.engine import StoreConnection, connect
from sentinel.persistence.migrate import current_revision, head_revision
from sentinel.registration import register_all


class StoreNotReadyError(Exception):
    """The store's schema is missing or not at the version this code expects."""


@dataclass(frozen=True)
class AppContext:
    """Shared CLI state: a store connection whose schema is up to date."""

    conn: StoreConnection


def build_context() -> AppContext:
    """Register all implementations and open the store.

    Raises StoreNotReadyError if migrations haven't been applied. The CLI
    never changes the schema itself; run ``sentinel db upgrade`` once per deploy.
    """
    register_all()
    conn = connect()
    current, head = current_revision(conn), head_revision()
    if current != head:
        conn.close()
        raise StoreNotReadyError(
            f"Store schema is at revision {current or 'none'}, expected {head}. "
            "Run `sentinel db upgrade`."
        )
    return AppContext(conn=conn)
