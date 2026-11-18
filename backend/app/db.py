"""Small psycopg connection-pool wrapper."""
from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def _configure(conn: Connection) -> None:
    # Typo-tolerant name search: lets "hart" match "heart" through the GIN index.
    conn.execute("SET pg_trgm.word_similarity_threshold = 0.4")
    conn.commit()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=5,
            open=False,
            configure=_configure,
            kwargs={"row_factory": dict_row},
        )
        _pool.open(wait=True, timeout=10)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def fetch_all(sql: str, args: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        return conn.execute(sql, args).fetchall()


def fetch_one(sql: str, args: list[Any] | tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        return conn.execute(sql, args).fetchone()
