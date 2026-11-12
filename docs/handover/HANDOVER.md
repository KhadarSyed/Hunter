# Hunter Intelligence Platform: Handover

*Rewritten 2026-11-12 from the code as it is today (the 2026-09-08 version described the old `agent/` layout, two
SQLite files and products since deleted). Where this file and the code disagree, the code wins: fix this file.*

The detailed, maintained references are `CLAUDE.md` (architecture, rules, commands) and `Instructions/README.md`
(standing rules, current state) plus `Instructions/log/` (one note per change, newest last). This page is the short
version for someone picking the project up.

## What it is

A research platform for PR/media analysis. A **research project** runs brief -> scope -> background research ->
search strategy -> matching label + data set (upload, tag, review) -> research plan -> deliverables (a branded
PPTX/Word/HTML deck built from the approved data). A separate **QC flow** cleans Meltwater/Empower Excel exports.
Organisations, users and roles (Super Admin, Admin, Analyser) with per-organisation LLM providers, guardrails,
exclusions, usage and billing.

## Stack

| Layer | What |
|---|---|
| Frontend | React 18 + TypeScript + Vite 5 + Tailwind CSS 4 (`frontend/`); `npm run build` writes into `backend/static/` |
| Backend | FastAPI, one process (`backend/main.py`), feature folders `backend/domains/<stage>/` |
| Database | Postgres 16 + pgvector, `DATABASE_URL` required. Queries: SQLAlchemy Core (`core/sa.py` + each domain's `models.py`). Schema: Alembic (`backend/migrations/`, applied at startup by `core/migrate.py`) |
| Files | S3 (`core/object_store.py`, `AWS_*`) for decks, logos/favicons, uploads, avatars and QC files; without S3 keys, Postgres/disk fallbacks |
| LLM | Each organisation's own providers (Settings -> LLM Providers: OpenAI-compatible, Azure OpenAI, Anthropic, Gemini), tried in order; the platform Azure OpenAI (`AZURE_OPENAI_*`) only for organisations flagged to use it. Embeddings: `EMBEDDING_MODEL_*` / `NVIDIA_EMBED_*` |

## Run it locally

1. Copy `.env.example` to `.env`. Only `DATABASE_URL` is required; every other variable is listed and explained there.
   `SEED_SUPER_ADMIN_EMAIL` / `SEED_SUPER_ADMIN_PASSWORD` create the first Super Admin on an empty database.
2. `powershell -ExecutionPolicy Bypass -File deploy/start-all.ps1` starts Docker Postgres (port 5433), the backend on
   http://localhost:8002 (also serves the built SPA) and Vite on http://localhost:5173. `deploy/stop-all.ps1` stops them
   (a backend restart ends running deck/tagging jobs: check first).
3. The first start creates the schema (Alembic). A database built before Alembic is stamped, not rebuilt.

## Deploy

- Backend: Docker image from `deploy/Dockerfile` (build from the repo root), on Render (`deploy/render.yaml` is the
  reference; auto-deploy from `main`). Frontend: Vercel (`frontend/vercel.json` forwards `/api` to the backend).
- `CORS_ORIGINS` (comma list of exact origins, never `*`) only when the frontend calls the API from another origin.

## Change the code

- New SQL goes into the owning `domains/<stage>/repository.py` (Core, its `models.py`); services call it through
  `core/store.py`.
- A schema change is an Alembic revision:
  `PYTHONPATH=. python -m alembic -c backend/alembic.ini revision -m "what changes"`, write `upgrade()`/`downgrade()`,
  add the columns to the domain's `models.py`, restart.
- Checks: `python -m ruff check backend`, `python -m vulture backend --min-confidence 80 --exclude backend/static`,
  `python -m pytest -q tests` (tests are local, not in git), `cd frontend && npx tsc --noEmit && npm run lint && npm test`.

## Known limitations

See `CLAUDE.md` "Known Issues" (no Meltwater API: Boolean queries are syntax-checked only; brand disambiguation in web
research is incomplete; hand-rolled URL routing on purpose).
