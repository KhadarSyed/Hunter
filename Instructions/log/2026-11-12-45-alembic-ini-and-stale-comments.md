# 2026-11-12-45 alembic.ini trimmed and documented; stale pg.py mentions removed

**Request:** "alembic.ini could say so. remove unwanted / Two comments in domains/billing/ still mention pg.py.
fix and continue" (the two deferred minors from the final review, log 44).

**Changed:**
- `backend/alembic.ini`: says how to handle a database built before Alembic (start the app once, it stamps it at
  0001, or `stamp 0001`, before a CLI `upgrade`); the `[loggers]/[handlers]/[formatters]` sections removed: nothing
  read them (`migrations/env.py` never calls `fileConfig`).
- `domains/billing/models.py`, `domains/billing/repository.py` docstrings: no longer describe the finished move off
  `core/pg.py`. `core/sa.py` comment keeps its reason without naming the deleted file.

**Verified:** `alembic -c backend/alembic.ini current` -> `0001 (head)` on the local DB; `tests/core/test_migrations.py`
+ `tests/qc` passed; `ruff` clean; no `pg.py` mention left in `backend/`. Comment/config-only change: no restart needed
(the CLI file is not read by the running app).
