# 2026-11-12-40 Plan task 5: startup migrations through Alembic; the local database is stamped

**Request:** executing the approved Alembic + hosted storage plan.

**Added:** `backend/core/migrate.py` `run()`: under `pg_advisory_xact_lock` (taken before `CREATE SCHEMA`, which
races even with IF NOT EXISTS): a legacy database (`schema_migrations` at 53, no `alembic_version`) is stamped at
`0001` and nothing is re-created; an older legacy one raises with a clear message; anything else is upgraded to head.
`core.db.init_intelligence_db()` now just calls it (same name for `main.py`, `deckstudio/cli.py`, test fixtures).

**Verified:** `tests/core/test_migrations.py` RED (no migrate module) -> GREEN 6/6 (empty upgraded twice, legacy
stamped with its data kept, legacy 52 refuses, 3 concurrent runs -> one version row). Full suite 632 passed (every
test schema now built by Alembic). Real local DB: first start logged "Database schema stamped", second "upgraded";
row counts identical before/after (projects 0, organizations 3, users 1, providers 3, asset library 11, usage 28).

**Also fixed (tests, local):** `tests/db_helpers.connect()` now creates the test schema before pointing at it; with a
missing schema, search_path fell through to `public` (the real data). Caught by a failing test, nothing written.

**Still present (task 6 deletes):** `core/pg.py`, the schema scripts and MIGRATIONS in `core/db.py` (now unused at
startup).
