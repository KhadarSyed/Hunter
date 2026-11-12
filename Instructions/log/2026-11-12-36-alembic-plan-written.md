# 2026-11-12-36 Implementation plan for Alembic + hosted storage (awaiting review)

**Request:** "greate now continue" (taken as approval of the spec
`docs/superpowers/specs/2026-11-12-alembic-and-hosted-storage-design.md`).

**Done:** plan written to `docs/superpowers/plans/2026-11-12-alembic-and-hosted-storage.md` (local, gitignored):
8 tasks: 1 QC source cache on SQLAlchemy; 2 freeze the 97 schema links + path columns into `projects/links.py`;
3 tests get `tests/db_helpers.py` (26 `_conn` uses in 13 files); 4 Alembic scaffold + baseline revision `0001`
(pg_dump of a FRESH database built by today's code, proven equal to an Alembic-built one); 5 `core/migrate.py`
(advisory lock; legacy DB at version 53 is stamped, older refuses, else upgrade); 6 delete `core/pg.py` and the schema
scripts; 7 avatars in S3 (same `/uploads/avatars/` URLs); 8 QC uploads and exports in S3.

**Facts checked for it:** Alembic 1.20 installed but not in requirements; last legacy migration 53 (52 rows);
`qc_source_cache` columns; `declared_foreign_keys()` = 97 links; the old bootstrap does not create
`intel_asset_library` inside test schemas (hence the fresh-database baseline); QC export names are not unique (S3 key
includes the run id).

**Not done:** no code changed; waiting for the user's review of the plan.
