# 2026-11-12-39 Plan task 4: Alembic scaffold and baseline revision 0001

**Request:** executing the approved Alembic + hosted storage plan.

**Added:** `backend/alembic.ini` (CLI), `backend/migrations/env.py` (uses the connection core/migrate.py passes, else
DATABASE_URL; target schema = test schema or public), `script.py.mako`, `versions/0001_baseline.py` (runs
`baseline.sql` as raw driver SQL; downgrade refuses), `backend/migrations/baseline.sql` (2663 lines, 117 tables).
`alembic>=1.13,<2` added to `backend/requirements.txt` (1.20 was installed but unlisted).

**How the baseline was made:** a fresh database `hunter_baseline` in the local container, built by today's
`init_intelligence_db()` (public schema, so `intel_asset_library` + the vector extension exist), dumped with
`pg_dump --schema-only --no-owner --no-privileges --no-comments`; `schema_migrations` statements (5) removed (old
runner's history), `public.` qualifiers stripped, `CREATE EXTENSION vector WITH SCHEMA public` first.

**Verified:** a second fresh database `hunter_alembic` built only by `alembic upgrade head` vs `hunter_baseline`:
columns equal (1244, incl. types, nullability, defaults), indexes equal (273), constraints equal (131), extensions
equal (2). Both temporary databases dropped. `tests/core/test_migrations.py`: baseline builds 117 tables + alembic_version
in an empty test schema, downgrade refused -> 2 passed. Startup still uses the old bootstrap (task 5 switches it).
