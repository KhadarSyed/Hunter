# 2026-11-12-37 Plan tasks 3 + 1: test DB helper; QC source cache on SQLAlchemy

**Request:** execute the approved plan (`docs/superpowers/plans/2026-11-12-alembic-and-hosted-storage.md`), "all good".

**Task 3 (tests only, local):** new `tests/db_helpers.py` (`connect()` = psycopg on the test schema, rows readable
as row[0]/row["col"]/dict(row), `%s` placeholders; `drop_schema()`); all 15 test files that used `core.db._conn`
converted (incl. the 3 e2e_3org scripts, whose non-SQL `?` in URLs/JS were restored by hand). Full suite 624 passed.

**Task 1:** `qc_source_cache` in `domains/qc/models.py` (live columns); `get_cached_source` / `upsert_source_cache`
moved from `core/db.py` to `domains/qc/repository.py` (Core; `__all__`, so `store.*` callers in
`qc/source_retrieval.py` are unchanged). Test `tests/qc/test_source_cache_repo.py`: RED (no attribute) -> GREEN
(insert, partial update keeps other fields, fetched_at advances). `ruff` clean.
