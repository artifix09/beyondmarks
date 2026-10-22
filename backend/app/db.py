"""The one connection pool.

The browser never talks to Postgres. FastAPI holds the service-role connection,
RLS stays on with no client policies, and answer keys therefore cannot leak to a
student who opens the network tab.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def dsn() -> str:
    """Postgres DSN for the Supabase project.

    Supabase exposes the pooler host in the dashboard under Project settings →
    Database. Set SUPABASE_DB_URL when it differs from the default derivation.
    """
    settings = get_settings()
    if not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL is not set")
    raise NotImplementedError(
        "M1: paste the Supabase connection string handling here once the "
        "project exists. Until then the API runs without a database."
    )


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(dsn(), min_size=1, max_size=5, open=True)
    return _pool


@contextmanager
def connection() -> Iterator[Connection]:
    with get_pool().connection() as conn:
        conn.row_factory = dict_row
        yield conn


def fetch_all(sql: str, params: Any = None) -> list[dict]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql: str, params: Any = None) -> dict | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()
