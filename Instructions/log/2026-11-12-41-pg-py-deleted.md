# 2026-11-12-41 Plan task 6: core/pg.py and the hand-written schema deleted

**Request:** executing the approved Alembic + hosted storage plan.

**Deleted:** `backend/core/pg.py` (303 lines, the sqlite3-style adapter); in `backend/core/db.py` (1894 -> 25 lines):
`_conn`, `INTELLIGENCE_SCHEMA`, `QC_SCHEMA`, `MIGRATIONS`, `_apply_migrations`, `_relocate_data_paths`,
`declared_foreign_keys` + its regexes, `table_names`/`table_columns`. Kept: `MISSING_DATABASE`, `schema_for_tests`,
`init_intelligence_db` (calls `core/migrate.py`). Local tests of the deleted code removed (`test_pg_pool`,
`test_pg_translate`, `test_links_frozen`).

**Fixed while verifying:** the Alembic CLI did not read `.env` (`alembic upgrade` failed with "DATABASE_URL is not
set" unless exported); `migrations/env.py` now loads `REPO_ROOT/.env` on the CLI path, like `main.py` does.

**Docs:** CLAUDE.md backend layout (`sa.py`, `migrate.py`, `migrations/`), repository rule, Database bullet (Core
everywhere; schema = Alembic; how to add a revision); README backlog item closed. requirements comments updated.

**Verified:** `ruff` clean; vulture only the known `handle_decl` false positive; full suite 617 passed (632 minus the
15 deleted tests of pg.py); migration tests 6 passed; a throwaway revision (add/drop a column) ran up and down through
the CLI in a test schema, then was deleted; backend restart (debug): "Database schema upgraded", `/api/health` ok,
browser walk 21 pages 0 problems, `verify_assets.py` 0 failed, 0 errors in the log.
