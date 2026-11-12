"""SQLAlchemy access for the domains moved off core/pg.py (billing first; see Instructions/README "Reviewer backlog").

One pooled engine per process on the same psycopg driver: pool_size + max_overflow cap the open connections,
pool_pre_ping replaces a connection the server dropped. Use `with sa.begin() as conn:` — commits on success,
rolls back on error, and always returns the connection to the pool."""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine

from .db import MISSING_DATABASE, schema_for_tests

POOL_SIZE = 5
MAX_OVERFLOW = 10          # at most POOL_SIZE + MAX_OVERFLOW open connections; callers wait beyond that
POOL_TIMEOUT_S = 30
POOL_RECYCLE_S = 1800


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(MISSING_DATABASE)
    for prefix in ("postgresql://", "postgres://"):       # plain URLs → the psycopg 3 driver already installed
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@lru_cache(maxsize=4)
def _engine(url: str) -> Engine:
    return create_engine(url, pool_size=POOL_SIZE, max_overflow=MAX_OVERFLOW, pool_timeout=POOL_TIMEOUT_S,
                         pool_recycle=POOL_RECYCLE_S, pool_pre_ping=True)


@contextmanager
def begin() -> Iterator[Connection]:
    with _engine(_url()).begin() as conn:
        if schema := schema_for_tests():
            conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
        yield conn
