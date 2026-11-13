# 2026-11-13-14 Frontend rebuilt so port 8002 shows the US labels

## Request
"continue" (everything open except the batching A/B comparison, which stays paused until GPT spend is approved).

## Checked open follow-ups (logs 03-13)
- `backend/static/index.html` was built at 08:32, before the US-English commit b0cf572 (12:50), so the SPA served on
  port 8002 still showed "Brand colours" / "All organisations". Vite on 5173 was already current.
- `tests/e2e_3org/run.py` (log 03 said its checkout steps were stale): already uses "Apply plan" and the read-only
  subscription tab; no checkout step left. Nothing to change.

## What changed
- `npm run build` in `frontend/` (writes `backend/static/`, gitignored). No source change.

## Verified
- New bundle `index-CehBQJte.js`: 0 files with "Brand colours" / "All organisations" / "analysing"; "Brand colors" present.
- `GET http://127.0.0.1:8002/` = 200 and references `assets/index-CehBQJte.js`.

## Not verified
- `tests/e2e_3org/run.py` not run (creates three orgs and sends emails; needs approval).
- Still open and paused: A/B batching comparison and a full NVIDIA brief/deck run (no GPT spend, no new projects).
- Untracked `cookie.json` at the repo root is not ignored by `.gitignore`; left untouched and never committed.
