# 2026-11-12-44 Final review of the Alembic + storage plan; Python bools stored as integer flags again

**Request:** "continue" (finish the plan: final whole-change review).

**Review:** one independent reviewer (fresh context, most capable model) over a88942e..d94cbb9 with the plan, spec,
Review Focus and the executor's rulings. Focus 1-5 checked sound (legacy DB stamped not rebuilt; older refuses; the
advisory xact lock held through stamp+upgrade inside one transaction, no nesting, SET LOCAL not leaking to pooled
connections; fresh DB equality; S3 fallbacks no-op without keys; QC download still access-checked; avatar regex
blocks traversal; deploy files tracked).

**Important finding, fixed:** the old core/pg.py turned Python bools into ints for every query; SQLAlchemy sent them
as booleans and Postgres refused them in BIGINT flag columns. `qc/source_retrieval.py` passes
`is_accessible=(status == 200)`, so every QC run that reached a source URL raised inside the date-mismatch check and
`run_qc` swallowed it: a "clean" run with no date-mismatch findings. Fix in one place for every domain:
`core/sa.py` registers a psycopg dumper (`_BoolAsInt`) on every engine connection (the schema has no boolean
columns: information_schema checked). Test `tests/qc/test_source_cache_repo.py::test_python_bools_are_stored_as_integer_flags`
RED (CannotCoerce boolean -> bigint) -> GREEN; full suite 624 passed; restart, browser walk 21/0, assets 0 failed.

**Deferred minors (not fixed, user decides):**
- The Alembic CLI on a database built by the old bootstrap (never started since) runs the baseline and fails with
  DuplicateTable (rolled back, harmless); the app's startup stamps it instead. One line in alembic.ini could say so.
- Stale docstrings still mention pg.py: `domains/billing/models.py:3`, `domains/billing/repository.py:2`.

**Reviewer declined to judge:** S3 `ResponseContentDisposition` with non-ASCII/quote file names; the QC export
redirect in a browser (no QC pages remain in frontend/src); `CREATE EXTENSION vector` privileges on Render.
