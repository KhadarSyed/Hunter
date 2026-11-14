# 2026-11-14-11 API_KEY: signed-in pages no longer need it; scripts still do

## Request
- "API_KEY here mean which API key llm model ?" → it is not an LLM key: it is the app's own shared secret for its
  `/api/intel` API (header `X-API-Key`).
- "ok continue" → approve the suggested change: a live session cookie is enough, so setting `API_KEY` (required when
  `ENVIRONMENT=production`) can no longer lock the app's own pages out (log 2026-11-14-10).

## What changed
- `backend/core/api.py` `require_api_key`: passes when API_KEY is unset, when the right `X-API-Key` is sent, or when
  the request carries a live session cookie (`store.get_session_user`). Otherwise 401 "Invalid or missing API key",
  as before.
  - Cost: one session lookup per `/api/intel` request, and only when API_KEY is set and no key was sent.
- `backend/core/config.py`: the `api_key` comment no longer claims the WebSocket takes `?api_key=`. Nothing reads it:
  `/ws` uses a ticket or the session cookie (`core/events._socket_user`).
- `.env.example`: the `API_KEY` line says what it is (this app's own secret, not an LLM key) and that signed-in users
  never need it.

## Verified
- `tests/security/test_access_and_hardening.py::test_api_key_or_live_session`, 5 cases with API_KEY set:
  - pass: the right key; a live session with no key.
  - 401: an ended session, nothing, a wrong key.
- ruff clean; `pytest -q tests` (minus e2e_3org): 751 passed.
- Backend restarted (no jobs or runs; Azure blanked): `/api/health` 200. `/api/intel/projects` with no session
  answers 401 from the session check (API_KEY is empty locally).

## Not verified / open
- Not run with API_KEY set on a live server (covered by the test above only).
- Render's real env vars were not read; nothing was changed there.
