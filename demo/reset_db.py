"""Recreate the demo database and apply migrations (used by run_demo.sh).

Drops and recreates the database named in SENTINEL_DATABASE_URL, so point it
at a throwaway database (run_demo.sh uses ``sentinel_demo``).
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from sentinel.persistence import migrate
from sentinel.persistence.engine import database_url

url = database_url()
parts = urlsplit(url)
name = parts.path.lstrip("/")
if not name or name == "sentinel":
    raise SystemExit(f"Refusing to reset {name!r}; point SENTINEL_DATABASE_URL at a demo database.")
maintenance_url = urlunsplit(parts._replace(path="/postgres"))

with psycopg.connect(maintenance_url, autocommit=True) as conn:
    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

migrate.upgrade(url)
print(f"Demo database {name!r} ready.")
