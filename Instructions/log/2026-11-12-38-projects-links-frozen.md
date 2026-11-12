# 2026-11-12-38 Plan task 2: schema links frozen into projects/links.py

**Request:** executing the approved Alembic + hosted storage plan.

**Changed:** new `backend/domains/projects/links.py`, generated from the old parser: `DECLARED_LINKS` (97 (child,
column, parent) links that `core/db.declared_foreign_keys()` read out of the CREATE TABLE scripts) and
`PATH_COLUMNS` (= `core.db._PATH_COLUMNS`). `projects/repository.py` uses them instead of importing `core.db`, so
project deletion no longer depends on the schema scripts Alembic replaces.

**Verified:** `tests/projects/test_links_frozen.py` RED (cannot import links) -> GREEN (equal to the parser's output,
both lists); `pytest tests/projects` 20 passed; `ruff` clean. The equality test is deleted with the parser (task 6).
