"""Apply db/migrations/*.sql in filename order. Safe to run repeatedly.

    python -m app.migrate
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg

from .config import get_settings

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def migrate(database_url: str | None = None, directory: Path | None = None) -> list[str]:
    """Apply pending migrations and return the names that were applied."""
    directory = directory or Path(os.getenv("MIGRATIONS_DIR", DEFAULT_DIR))
    applied_now: list[str] = []
    with psycopg.connect(database_url or get_settings().database_url) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(directory.glob("*.sql")):
            if path.name in done:
                continue
            # One transaction per migration: it fully applies or not at all.
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
    return applied_now


if __name__ == "__main__":
    names = migrate()
    print("applied:", ", ".join(names) if names else "nothing (already up to date)")
