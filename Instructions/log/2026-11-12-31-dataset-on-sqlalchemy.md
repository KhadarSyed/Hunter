# 2026-11-12-31 Dataset domain on SQLAlchemy Core (last domain repository)

**Request:** "please continue your journey" (remaining list item 1: dataset domain to SQLAlchemy).

**Changed:**
- New `backend/domains/dataset/models.py`: `intel_upload_files`, `intel_articles`, `intel_article_rq`,
  `intel_theme_titles` with the exact live columns (read from information_schema), plus the two foreign columns
  this domain touches (`intel_projects.dataset_approved_*`, `intel_deliverable_runs.status`).
- `backend/domains/dataset/repository.py` rewritten in Core (same 44 public functions, signatures, dict keys).
  Id lists bind as one array parameter (`= ANY(:array)`, `_ids`/`_texts`) however long; multi-row inserts
  (articles, RQ match rows, decide-created rows) are batched 1000 rows per statement (Postgres 65535-parameter cap);
  `UPDATE ... FROM` via aliases, `ON CONFLICT ... WHERE`, JSONB paths (`#>>` via `JSONB[...]`), LATERAL
  `jsonb_array_elements` for the brand facet, executemany for `undo`.
- Tests (local): `test_router::test_decide_uses_array_params` now spies via a SQLAlchemy `before_cursor_execute`
  listener; `test_tagging_job` uses a local `_sql` helper instead of `repo._run`.

**Verified:**
- Old (HEAD) vs new in a throwaway schema (scratchpad `dataset_parity.py`): 207 comparisons, 0 differences: every
  write step (state compared with ids mapped to URLs), every read on both projects, 21 filter combinations for
  `page`/`ids_matching`, facets per channel, decide/undo incl. created rows, 2500-row insert across chunks.
- `pytest tests/dataset tests/deliverable tests/deckstudio tests/strategy` -> 258 passed. `ruff` clean.
  No `_conn`/`pg.py` left in `domains/dataset/`.

**Next:** direct `_conn()` callers outside repositories: core/auth.py, core/db.py, core/store.py,
assets/library.py, datasources/router.py, deckstudio/assets.py, guardrails/router.py,
research/article_extractor.py, main.py; then retire `core/pg.py` (Alembic spec first, for approval).
