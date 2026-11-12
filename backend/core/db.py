"""Database bootstrap: DATABASE_URL is required (Postgres only); the schema is managed by Alembic
(backend/migrations, run at startup by core/migrate.py). Queries go through core/sa.py + each domain's models.py."""

from __future__ import annotations

import hashlib
import os

from . import config

MISSING_DATABASE = ("DATABASE_URL is not set. Hunter runs on Postgres only: start the local database with "
                    "`docker compose -f deploy/docker-compose.postgres.yml up -d` and set DATABASE_URL in .env.")


def schema_for_tests() -> str | None:
    """Tests (HUNTER_PG_SCHEMA_PER_DB): each throwaway DB path is its own Postgres schema; None in normal runs."""
    if not os.environ.get("HUNTER_PG_SCHEMA_PER_DB"):
        return None
    return "t_" + hashlib.sha1(str(config.MEMORY_DB_PATH).encode()).hexdigest()[:16]


def init_intelligence_db() -> None:
    """The schema, via Alembic (core/migrate.py)."""
    from . import migrate      # local: migrate imports sa, which imports this module
    migrate.run()
