"""Alembic environment: the app's own connection when core/migrate.py passes one, else DATABASE_URL. Migrations run
in the test schema when HUNTER_PG_SCHEMA_PER_DB is set, else in public."""
from alembic import context
from sqlalchemy import create_engine

from backend.core.db import schema_for_tests
from backend.core.sa import _url


def _run(conn) -> None:
    schema = schema_for_tests() or "public"
    conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
    context.configure(connection=conn, target_metadata=None, version_table_schema=schema)
    with context.begin_transaction():
        context.run_migrations()


given = context.config.attributes.get("connection")
if given is not None:
    _run(given)
else:      # the alembic CLI: read .env like the app does (main.py), so DATABASE_URL needs no export
    from dotenv import load_dotenv

    from backend.core.config import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env")
    with create_engine(_url()).begin() as conn:
        _run(conn)
