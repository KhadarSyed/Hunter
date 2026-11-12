# 2026-11-12-32 Direct database calls outside repositories moved to SQLAlchemy

**Request:** "please continue your journey" (remaining list item 2: the direct `_conn()` callers).

**Changed (same behaviour, no `_conn`/`pg.py` left outside core/db.py and core/pg.py):**
- `core/auth.py`: `_project_id_by_sql` (raw SQL strings) deleted; the clarification/plan/QC run/finding/export access
  checks call new owner lookups: `spec.get_clarification_project_id`, `plan.get_plan_project_id`,
  `qc.get_qc_run_project_id` / `get_qc_finding_project_id` / `get_qc_export_project_id` (all in `__all__`).
- `organizations.allow_editorial_images`: `auth.repository.get_allow_editorial_images` / `set_allow_editorial_images`,
  used by `deckstudio/assets.py` and the `guardrails/router.py` policy routes.
- `datasources/router.py`: the Default Organization lookup uses the existing `find_organization_by_name`
  (case-insensitive, was exact).
- `research/article_extractor.py`: its cache table `research_article_fulltext` is in `research/models.py`;
  `get_article_fulltext` / `save_article_fulltext` in the research repository.
- `assets/library.py` + `assets/models.py` (`intel_asset_library`): Core with the pgvector package's `Vector` type
  and `cosine_distance`; `pgvector>=0.3,<1` added to `backend/requirements.txt` (was installed locally, not listed).
- `main.py` health check: `SELECT 1` via `sa.begin()`. `core/store.py`: unused `_conn` re-export removed.

**Verified:** `ruff` clean; full suite `pytest tests --ignore=tests/e2e_3org` -> 624 passed; asset library old vs new
(scratchpad `library_parity.py`): 14 comparisons, 0 differences (upsert keeps the embedding, brand/role filters,
scores, touch, delete); backend restarted (debug): `/api/health` ok, `verify_assets.py` 0 failed, 0 log errors.

**Incident (found and cleaned):** my parity scripts did not set `HUNTER_PG_SCHEMA_PER_DB=1`, so they wrote to the
local `public` schema instead of a throwaway one: projects 5/6 (`p5`/`p6`, 5002 articles, 3600 RQ rows, 2 files,
4 titles, 1 deck run) and 6 `intel_asset_library` rows of kinds `o`/`n`. Removed via `projects.delete_project` and a
kind-scoped delete; all 40 project tables re-checked empty. Real rows (8 asset-library rows, 13 llm_usage rows with
no project) untouched. **Rule:** a parity/throwaway script must set `HUNTER_PG_SCHEMA_PER_DB=1` before importing
backend; `intel_asset_library` exists only in `public` (vector extension), so tests of it write there.

**Left in core/db.py:** schema bootstrap + MIGRATIONS, `get_cached_source` / `upsert_source_cache`,
`declared_foreign_keys` (parses the MIGRATIONS text; projects deletion relies on it) -> the Alembic spec.
