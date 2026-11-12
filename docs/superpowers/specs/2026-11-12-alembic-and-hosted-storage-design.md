# Retire `core/pg.py` for Alembic, and close the hosted-storage gaps

Date: 2026-11-12. Status: draft for review. Owner decisions already taken: keep the legacy tables of the deleted
products in the baseline (Q3 = A); work locally only.

## Why

The reviewer's complaint was hand-written SQL and a home-made migration runner. Every domain repository and every
direct call now uses SQLAlchemy Core (logs 04-32). What is left:

- `core/pg.py`: a sqlite3-style adapter that translates `?` SQL for Postgres. Used only by `core/db.py` now.
- `core/db.py`: two big `CREATE TABLE` scripts (`INTELLIGENCE_SCHEMA`, `QC_SCHEMA`), a list of 51 hand-numbered
  `MIGRATIONS`, its own `schema_migrations` table, a one-off path rewrite (`_relocate_data_paths`), the QC source
  cache helpers, and `declared_foreign_keys()` (which parses the SQL text above; project deletion relies on it).
- Two kinds of file that live only on the server's disk (see Part B), so a hosted restart loses them.

Success = no `pg.py`, no hand-written schema scripts, schema changes as ordinary Alembic migrations, every user file
also in S3 when S3 is configured, and no change in behaviour.

## Part A: Alembic

### A1. Small moves first (no schema change)
- `get_cached_source` / `upsert_source_cache` (QC link checks) -> `domains/qc/repository.py` + `qc_source_cache` in
  `qc/models.py`, Core like the rest. Caller `qc/source_retrieval.py` keeps calling `store.*`.
- `declared_foreign_keys()` -> frozen: its current output (read once, today) becomes a constant list in
  `projects/repository.py`, next to `_UNDECLARED_LINKS`. Tables with a `project_id` column are still discovered from
  the live schema, so a new project table needs no list entry; a new table linked another way is added by hand, as
  `_UNDECLARED_LINKS` already requires.
- `_PATH_COLUMNS` (used by project deletion to find files) moves to `projects/repository.py`.

### A2. Baseline = a snapshot of today's schema (chosen approach)
Alternatives rejected: re-typing the 51 migrations as Alembic steps (slow, error-prone, adds nothing); generating the
baseline from the SQLAlchemy models (they do not declare the legacy tables or most server defaults, so new databases
would differ from existing ones).

- Build a fresh database with today's code (`init_intelligence_db` into an empty schema), take
  `pg_dump --schema-only --no-owner --no-privileges` of it (the `hunter-postgres` container has pg_dump 16), and
  check it in as `backend/migrations/baseline.sql`.
- `backend/migrations/` = standard Alembic layout: `env.py` (URL from `DATABASE_URL` via `core/sa.py`, honours
  `schema_for_tests()` so tests migrate their own `t_*` schema), `versions/0001_baseline.py` whose `upgrade()`
  executes `baseline.sql` (incl. `CREATE EXTENSION IF NOT EXISTS vector` and the legacy tables) and whose
  `downgrade()` refuses (a baseline is not reversible). `alembic.ini` at `backend/`.
- New dependency: `alembic` (SQLAlchemy's own migration tool) in `backend/requirements.txt`.

### A3. Startup (`core/db.init_intelligence_db` becomes `core/migrate.py`)
Under a Postgres advisory lock (two workers starting together must not both migrate):
1. `alembic_version` table exists -> `alembic upgrade head`.
2. Else `schema_migrations` exists and its highest version is the last legacy one -> `alembic stamp 0001`
   (marks the existing database as being at the baseline; nothing runs or changes), then `upgrade head`.
3. Else `schema_migrations` exists but is older -> refuse to start with a clear message (that database must first run
   the last pre-Alembic release once). Local is current; the Render database is suspended.
4. Else (empty database) -> `alembic upgrade head`.

`schema_migrations` is left in place (data, not code); nothing reads it after the stamp.

### A4. Delete
`core/pg.py`; in `core/db.py`: `_conn`, `INTELLIGENCE_SCHEMA`, `QC_SCHEMA`, `MIGRATIONS`, `_apply_migrations`,
`_relocate_data_paths` and the regexes. `core/db.py` keeps only what is still used (`schema_for_tests`,
`MISSING_DATABASE`, `table_names`/`table_columns` if still called). The 9 test spots that use `core.db._conn` move
to a small SQLAlchemy helper in `tests/conftest.py` (local only).

### A5. Verification (must all pass before the delete is committed)
- Schema equality: fresh schema built by the old code vs fresh schema built by `alembic upgrade head`:
  `pg_dump --schema-only` of both, normalised (schema name), `diff` empty.
- Local database: stamped, `upgrade head` is a no-op, row counts unchanged.
- A throwaway `alembic revision` adding and dropping a column runs up and down cleanly.
- Full test suite; backend start in debug mode; `/api/health`; the logo/favicon S3 check.
- Docs: CLAUDE.md "Database" bullet and Quick Start (how to add a migration: `alembic revision -m ...`).

## Part B: hosted-storage gaps (bounded, same pattern as the Data set uploads)

Only matters on a server whose disk resets; local behaviour is unchanged. Without S3 keys everything works as today.

- **Avatars** (`auth/router.py`): the upload also goes to S3 (`avatars/user-{id}/{file}`); a new route
  `GET /api/auth/avatar/{user_id}` answers with a 307 to a signed S3 link (as logos do), else the local file. The
  stored `avatar_url` points at that route. Existing local avatar files keep working through the fallback.
- **QC upload** (`qc/router.py` -> `qc_reports.file_path`): the uploaded export also goes to S3
  (`qc/report-{id}/{file}`); readers go through one helper that restores the disk copy from S3 when it is missing
  (the Data set's `intel_dataset_files` restore, but S3 instead of Postgres bytes).
- **QC export** (`qc/export.py`): the written file also goes to S3 (`qc/exports/{id}/{file}`); the download route
  serves the disk copy, else redirects to S3.
- Tests: upload/restore/download with a fake S3 (as `tests/core/test_object_store.py`), and without S3.

## Order and size
A1 (small) -> A2+A3 (Alembic, with A5's schema diff) -> A4 (delete) -> Part B. Each step is its own commit, pushed
and restarted per the standing rules, with a log note. Part B is independent and can go first if preferred.

## Out of scope
Dropping the legacy tables (a later, separate migration); the Render database (suspended, untouched);
`frontend/vercel.json`'s backend host (Vercel cannot read env vars there).
