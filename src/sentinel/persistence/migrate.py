"""Runs Alembic migrations for the store (used by ``sentinel db upgrade``)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from sentinel.persistence.engine import StoreConnection, database_url

_SCRIPT_LOCATION = Path(__file__).parent / "migrations"


def sqlalchemy_url(url: str | None = None) -> str:
    """The store URL with the psycopg (v3) driver, as SQLAlchemy expects."""
    resolved = database_url(url)
    for prefix in ("postgresql://", "postgres://"):
        if resolved.startswith(prefix):
            return "postgresql+psycopg://" + resolved[len(prefix) :]
    return resolved


def _config(url: str | None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    config.attributes["url"] = database_url(url)
    return config


def upgrade(url: str | None = None, revision: str = "head") -> None:
    """Apply migrations up to ``revision``. Safe to run concurrently."""
    command.upgrade(_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    """Revert migrations down to ``revision`` (default: drop everything)."""
    command.downgrade(_config(url), revision)


def head_revision() -> str | None:
    """The newest migration shipped with this version of Sentinel."""
    return ScriptDirectory.from_config(_config(None)).get_current_head()


def current_revision(conn: StoreConnection) -> str | None:
    """The migration the database is at, or None if it was never migrated."""
    row = conn.execute("SELECT to_regclass('alembic_version')").fetchone()
    if row is None or row[0] is None:
        return None
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if version is None else str(version[0])
