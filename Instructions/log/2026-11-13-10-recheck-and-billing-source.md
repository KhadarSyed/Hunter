# 2026-11-13-10 Re-audit until clean; billing column renamed

## Request
"Do /ponytail:ponytail-audit /ponytail:ponytail-review and verify all the changes required all the hard coded are now
resolved and unsed code are removed, also remove empty folders / recheck again until nothing found to fix / for billing
please rename it, in future it wil be difficult".

## What changed
- **Billing column rename:** Alembic `0002_subscription_source.py`: `org_subscriptions.payment_ref` -> `source`
  ("granted" = Super Admin, "checkout" = rows of the removed test checkout). `billing/models.py`, `repository.py`
  updated; downgrade renames it back. `tests/core/test_migrations.py` reads the head revision instead of a hard-coded
  "0001", plus a test for the 0002 rename/value mapping.
- **Dead code removed (only tests or nobody called it):** `agents/question_tag_schema.review_mapping` (+ `_review_column`,
  `BUILT_IN_COLUMNS`, `FROM_REVIEW_TABLE`), `strategy/tag_schemas.with_also_questions`, `strategy/dimensions._union`,
  `deliverable/ingest._read_rows`, `deliverable/deck._source` (+ `LOGO_MAX_H`, `BRAND_PLOT_TOP/H`),
  `deliverable/latest24h.outlet_country` (production uses `outlet_countries`), the whole unimported
  `deliverable/classify.py`, `org_chat_clients.PROVIDER_TYPES` (duplicate of `providers/schemas.ProviderType`),
  `deckstudio/assets.LICENSED`, `memory/service.TYPES`, settings fields `brandfetch_api_key`, `brandfetch_client_id`
  (code reads the env vars directly), `llm_price_input/output_per_1m` (never read), frontend `utils/format.formatEpoch`.
  Their local tests deleted or moved to the production function (`outlet_countries`).
- **Hard-coding:** support address moved from `core/email_layout.SUPPORT_EMAIL` to settings `support_email`
  (env `SUPPORT_EMAIL`, added to `.env.example`, same default).
- **Deprecations / leaks:** `research/news_search` `datetime.utcnow()` -> `datetime.now(timezone.utc)` (naive, same
  value); Pillow `getdata()` -> `get_flattened_data()` in `deckstudio/logo_prep.py`, `deliverable/brand_kit.py`
  (requirements floor `Pillow>=12.3.0`, the tested version); `deckstudio/exporter.build_pdf` closes each slide PNG
  (Windows kept them locked) + test `tests/deckstudio/test_build_pdf.py`; `alembic.ini` `path_separator = os`.
- **Dependencies:** `httpx` moved from `requirements.txt` to `requirements-dev.txt` (only FastAPI's TestClient uses it).
- **Docs:** `README.md` Pexels key name; `Instructions/README.md` schema revision 0002; `.env.example` Pexels note.
- **Empty folders:** none left (`data/deliverables` is recreated by the running backend at startup; `.claude/worktrees` kept).

## Verified
- `ruff check backend` clean; vulture 80%: 0; vulture 60% after filtering decorated routes/validators/framework hooks
  and grepping every remaining name in backend, tests and frontend: 0 unused.
- Hard-coding grep (user paths, user name, company emails) outside `core/config.py`: none.
- `.env.example` vs the 53 env vars the code reads: all listed (WINDIR / RENDER_EXTERNAL_URL are platform-set).
- Frontend: `tsc --noEmit` clean, lint 0 errors (32 allowed warnings), `npm test` 14 passed; unused exports: none
  other than names used inside their own file.
- `pytest -q tests` (excluding e2e_3org): 647 passed; then `tests/deckstudio` 59 passed with `-W default`, no warnings.
  The remaining test-only warnings are psycopg pools evicted from `sa._engine`'s lru_cache as each test uses its own
  schema URL (production has one URL).

## Not verified
- The 0002 migration on the Render database (Render service suspended; applies itself at the next start).
- A real Brandfetch / Pexels call after the settings-field removal (the code never read those fields).
