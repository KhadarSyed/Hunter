"""Schema migrations at startup (Alembic, backend/migrations). One process at a time (advisory lock):
- a database the old core/db.py bootstrap built (schema_migrations at LEGACY_LAST, no alembic_version) is stamped at
  the baseline, then upgraded: nothing is re-created;
- an older legacy database refuses to start (run the last pre-Alembic release once first);
- anything else (empty, or already on Alembic) is upgraded to head."""
from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from . import config, sa
from .db import schema_for_tests

logger = logging.getLogger(__name__)
LEGACY_LAST = 53
BASELINE = "0001"
_LOCK_KEY = 0x48554E54          # "HUNT": one migrating process at a time


def _alembic(conn) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(config.BACKEND_DIR / "migrations"))
    cfg.attributes["connection"] = conn
    return cfg


def run() -> str:
    schema = schema_for_tests() or "public"
    with sa.begin() as conn:
        # the lock comes first: two processes creating the same schema at once collide even with IF NOT EXISTS
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
        conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
        tables = set(conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"),
                                  {"s": schema}).scalars())
        cfg = _alembic(conn)
        action = "upgraded"
        if "alembic_version" not in tables and "schema_migrations" in tables:
            last = conn.execute(text("SELECT MAX(version) FROM schema_migrations")).scalar() or 0
            if last < LEGACY_LAST:
                raise RuntimeError(f"The database is at legacy migration {last}; this release needs {LEGACY_LAST}. "
                                   "Start the last pre-Alembic release once, then this one.")
            command.stamp(cfg, BASELINE)
            action = "stamped"
        command.upgrade(cfg, "head")
    logger.info("Database schema %s (Alembic head)", action)
    return action
