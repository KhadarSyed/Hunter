# 2026-11-12 #01 — Reviewer cleanup: hard-coded config, .env.example, before/after protocol

## Request
Reviewer: too many hard-coded things and unused scripts/code, hard to run manually; DB is raw SQL instead of
SQLAlchemy models; the env file lists many unused things. Make the Instructions folder the before/after step of every
request, with rules against hallucination, for every new session. (/init: improve CLAUDE.md.)

## Changed
- `backend/core/config.py`: removed the legacy Brief-to-Deck `Settings` dataclass, `DEFAULT_SETTINGS`,
  `SETTINGS_PATH`, `load_settings`, `save_settings`, `ensure_dirs`. None of its fields was read anywhere, but
  `main.py` startup called `ensure_dirs(load_settings())`, which created folders under another user's OneDrive
  path (`C:\Users\sweta.shah\OneDrive - InfoVision, Inc\...`) on every machine that started the backend.
  `MEMORY_DB_PATH` kept (with a comment): `core/db.py` hashes it into the Postgres schema name.
- `backend/core/llm_provider.py`: `build_llm_client()`, `HybridLLMClient()`, `_build_chat_backend()` no longer take
  the unused `settings` argument. Callers updated: `core/llm_synthesis.py`, `domains/plan/service.py`, `get_llm_client()`.
- `backend/main.py`: dropped the `ensure_dirs(load_settings())` startup call and its imports.
- `.env.example`: rewritten from a grep of every env var the backend reads. Removed `ANTHROPIC_API_KEY` (unused),
  `HUNTER_AUTOFIX` (its supervisor was deleted), `PEXEL_API_KEY` (listed as `PEXELS_API_KEY`; code still accepts the
  old name). Added the missing `DATABASE_URL` (compose host port 5433), `ENVIRONMENT`, `API_KEY`, `WS_TICKET_SECRET`,
  `SEED_SUPER_ADMIN_PASSWORD`, `APP_URL`, `ZEPTO_*`, `AWS_*`, `EMBEDDING_MODEL_*`, research/photo keys, tuning knobs.
- `CLAUDE.md`: before/after protocol + no-hallucination rules at the top; fixed stale facts (no `supervisor.py`,
  `build_llm_client()` signature, `memory.db`); added start-all/stop-all, `.env.example`, interpreter and test commands.
- `Instructions/README.md`: same protocol and rules; new "Reviewer backlog" section.

## Verified
- `Python312\python.exe -c "import backend.main, backend.core.llm_provider, backend.core.llm_synthesis,
  backend.domains.plan.service"` → IMPORT_OK.
- grep: no remaining reference to `load_settings`, `ensure_dirs`, `save_settings`, `DEFAULT_SETTINGS`, `sweta.shah`
  in `backend/`; none in local `tests/` either.

## Not verified
- Backend not restarted; no LLM call run end to end after the signature change (import check only).
- The env var list was built by grepping `os.getenv/os.environ/env_setting` plus the `AppSettings` fields; a variable
  read some other way could be missing from `.env.example`.

## Not done (needs the user's decision)
- SQLAlchemy/Alembic migration (see README "Reviewer backlog").
- Deleting `domains/agent/qa_browser.py`; cleaning the local `.env` (not in git; the user's own keys).
