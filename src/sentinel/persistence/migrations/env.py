"""Alembic environment for Sentinel's store.

Migrations are plain SQL (no ORM models). The URL comes from
``config.attributes["url"]`` (set by ``sentinel db upgrade``) or, when running
the ``alembic`` CLI directly, from SENTINEL_DATABASE_URL.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool, text

from sentinel.persistence.migrate import sqlalchemy_url

# Serializes concurrent `upgrade` runs (e.g. several deploys starting at once).
_MIGRATION_LOCK_ID = 0x53454E54_4D494752  # "SENTMIGR"


def _sqlalchemy_url() -> str:
    return sqlalchemy_url(context.config.attributes.get("url"))


def run_migrations_offline() -> None:
    context.configure(url=_sqlalchemy_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_sqlalchemy_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=False)
        with context.begin_transaction():
            connection.execute(text(f"SELECT pg_advisory_xact_lock({_MIGRATION_LOCK_ID})"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
