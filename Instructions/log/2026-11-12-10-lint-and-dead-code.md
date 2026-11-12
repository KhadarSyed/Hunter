# 2026-11-12 #10 — ruff + vulture, dead code removed; settings consolidation dropped

## Request
"2": switch from the domain moves to the agreed package list.

## Decided
- Settings into `AppSettings` (61 env reads): DROPPED. ~22 of those variables are changed at runtime (tests'
  setenv/delenv, HUNTER_PG_SCHEMA_PER_DB, SEED_SUPER_ADMIN_*), and `get_app_settings()` is cached, so it would ignore
  them; ~40 tests would need cache resets for no behaviour gain. `.env.example` already lists every variable.

## Changed
- `ruff.toml` (new): F + E9, line length 120; `backend/requirements-dev.txt` (new): pytest, ruff, vulture.
- ruff fixes: 2 unused imports, 2 placeholder-less f-strings (query_evaluator, dataset/normalize, research/relations),
  2 imports left unused after the deletions.
- Deleted `core/llm_synthesis.py` (~340 lines, audit 10); its `_figures` moved unchanged into
  `deliverable/factcheck.py`, which `deckstudio/guards.py` already imported `_with_rounding` from.
- Removed unused functions (audit 12 + vulture, each grep-checked over backend/tests/frontend incl. strings):
  object_store.presign, HybridLLMClient.is_embed_reachable (+ its docstring mention), design_systems.shortlist,
  web_research LiveWebResearchAdapter.fetch_url/_extract_parent_company/_extract_products/_extract_audience/
  _extract_rqs, brand_intelligence WebResearchAdapter.fetch_url, brief/parser.guess_client_name,
  strategy/dimensions.dimensions_for_dataset, strategy/tag_schemas.schema_for_dataset,
  question_tag_schema.prompt_block (95 lines). Kept (tested locally): outlet_country, review_mapping,
  with_also_questions.
- Local test `tests/deliverable/test_run_setup_failures.py`: removed the test of llm_synthesis's pool thread.

## Verified
- `ruff check backend`: clean. `vulture --min-confidence 80`: only creative.py `decl` (HTMLParser signature).
- pytest deliverable, deckstudio, research, strategy, agents, core, spec: 304 passed, 12 failed — all pre-existing:
  10 known latest24h/time_grain, plus `test_live_slides` (label format) and `test_object_store::
  test_disabled_without_env` (cache_clear on the conftest stub); both also fail with today's changes stashed.
