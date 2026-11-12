# 2026-11-12-29 CORS origins: configurable, validated, documented

**Request:** "CORS also hard coded can you please check that also".

**Found:** `AppSettings.cors_origins` (`core/config.py`, used by `main.py` CORSMiddleware and the CSRF guard in
`core/api.py:102`) was already overridable via `CORS_ORIGINS`, but: not in `.env.example`; JSON-only; nothing refused
`"*"` (with `allow_credentials=True` Starlette then echoes any origin = any site acts as the signed-in user); the
hard-coded default listed `:8002` origins that were never needed (same-origin SPA; the CSRF guard passes same host).

**Changed:**
- `core/config.py`: `DEV_ORIGINS` (Vite 5173 only) default; `cors_origins` is `Annotated[list[str], NoDecode]` with a
  validator: blank -> default, comma list or JSON array, trailing `/` stripped, anything not `http(s)://host[:port]`
  (incl. `*`) refused at startup.
- `.env.example`: `CORS_ORIGINS=` documented. `deploy/render.yaml`: comment updated.
- `backend/requirements.txt`: `pydantic-settings>=2.7.0` (NoDecode; 2.15 installed).

**Verified:** settings parse table (unset/blank -> dev default; comma + JSON ok; `*`, `["*"]`, path, bare host,
`javascript:` rejected). Live backend (debug log, 0 errors): preflight from localhost:5173 -> 200 + ACAO echo;
from https://evil.example -> 400, GET gets no ACAO; POST from evil -> 403; POST from same host 8002 and from 5173 ->
200. Local `.env` does not set CORS_ORIGINS. `ruff` clean.

**Not changed:** `frontend/vercel.json` rewrites `/api` to the Render host by name: Vercel cannot read env vars in
vercel.json, so it stays (with that rewrite production calls are same-origin and need no CORS entry).
Render's CORS_ORIGINS value not inspected (no Render env changes).
