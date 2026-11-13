# 2026-11-13-08 Fixes 1-3 from the audit (note 07)

## Request
"fix 1, 2, 3".

## What changed
1. `backend/core/org_chat_clients.py` `OpenAICompatClient._stream`: new `cap` flag. A 400 now retries in steps:
   without `stream_options` (as before), then without `max_tokens`, so a model or vLLM server whose limit is below
   `MAX_OUTPUT_TOKENS` (16384) still answers instead of failing every call. A third 400 raises `ProviderCallError`.
2. `backend/domains/research/pexels.py`: new `_key()` reads `PEXELS_API_KEY` (the `.env.example` name, also what
   `deckstudio/assets.py` reads) and falls back to the older `PEXEL_API_KEY`; docstring names updated.
3. `deploy/start-all.ps1`, `deploy/stop-all.ps1`: the `hunter-objects` container handling removed (no container, no
   compose file; files go to AWS S3 via `core/object_store.py`).

## Verified
- `pytest -q tests/providers tests/research/test_pexels_key.py`: 34 passed (new: 400 twice -> retry without the cap;
  400 three times -> raises; both Pexels key names). `pytest -q tests/research`: 110 passed.
- `ruff check backend` clean; vulture (80%) nothing; both `.ps1` files parse with 0 errors (PowerShell parser).
- No running/queued `intel_jobs` before the restart.

## Not verified
- Fix 1 against a real model with a small output limit (unit test with a fake server only).
- `start-all.ps1` not run end to end (parse check only).
