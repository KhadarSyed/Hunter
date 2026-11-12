# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Every request: before and after (mandatory, every session)

`Instructions/` is the project's working memory. It is the first and last thing touched in every response.

**Before** answering or editing:
1. Read `Instructions/README.md` (map, standing rules, current state).
2. Read the newest 3-5 notes in `Instructions/log/` (newest first; names `YYYY-MM-DD-NN-topic.md`).
3. Open only the files those point to, then verify each fact you will rely on in the code itself.

**After** the work, in the same response:
1. Add `Instructions/log/YYYY-MM-DD-NN-topic.md` (next NN for the day): request, what changed (files, functions),
   how it was verified (commands + result), what was NOT verified, follow-ups.
2. Update the README's "Current state" / map if they changed. Commit the note with that response's work.

**No-hallucination rules** (the reviewer's main complaint was code and docs that did not match reality):
- Never state a file, function, env var, table, endpoint or default from memory or from a doc alone. Grep or read it
  first; docs here (including this file and old logs) go stale. If code and a doc disagree, the code wins: fix the doc.
- Every new env var goes into `.env.example` in the same change; one that is no longer read is removed from it.
- No hard-coded machine paths, user names, emails or hosts in code: use `core/config.py` constants or env vars.
- Report outcomes as measured: say "not verified" when you did not run it. Do not claim tests pass without output.
- Delete dead code instead of leaving it "for later"; before deleting, grep every caller (code and `tests/`).

## What this is

The **Hunter Intelligence Platform** (see `docs/CURRENT_STATUS.md` and `docs/handover/HANDOVER.md`):
a research pipeline (brief → scope → background research → search strategy → data sources →
research plan → deliverables, where the deck engine in `domains/deliverable/` + `domains/deckstudio/`
analyses the datasets and renders the branded PPTX/Word/HTML deck) plus a separate **QC flow** for
cleaning Meltwater/Empower Excel exports. Lives in `backend/domains/<stage>/` (one folder per stage,
see Backend layout below); `domains/__init__.py` mounts every stage router under `/api/intel`.

The old Brief-to-Deck folder-watcher product (`backend/deck/`) and the old evidence-library →
insights → storyline → slide-intelligence → composer → renderer → publishing chain were deleted;
their Postgres tables are left in place (no data dropped) but no code reads them.

## Repository layout

```
frontend/        React SPA (Vite); `npm run build` writes into backend/static/
backend/         FastAPI app — main.py, core/, domains/<stage>/, requirements.txt
  agents/        LLM agents (brief scope, query builder, enrichment, tag schemas, …)
data/            runtime data (gitignored) + the shipped house templates
deploy/          Dockerfile (build from the repo root), render.yaml (reference), start-all.ps1 / stop-all.ps1,
                 start.ps1, docker-compose.postgres.yml (local Postgres, host port 5433)
Instructions/    README (map, rules, current state) + log/ (one note per response) — read first, see above
docs/            product/subsystem docs, docs/handover/
.claude/skills/  Claude Code skills (deck-studio) — must stay here for Claude Code to load them
.mcp.json        MCP servers (Playwright, Brandfetch) — must stay at the repo root
```

## Quick Start

- **Everything at once:** `powershell -ExecutionPolicy Bypass -File deploy/start-all.ps1` (Docker Postgres, backend 8002,
  Vite 5173); `deploy/stop-all.ps1 [-Force]` stops them (check for running deck/tagging jobs first: a restart kills them).
- **Config:** copy `.env.example` to `.env`; it lists every variable the code reads (only `DATABASE_URL` is required
  locally). `.env` itself is local and may hold extra unused keys; the code ignores them.
- **Backend:** `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8002` from the repo root
  (or `.\deploy\start.ps1` / `Start Hunter Agent.bat` to build the frontend once and launch).
- **Frontend (dev):** `npm run dev` from `frontend/` — Vite on port 5173, proxies `/api` and `/ws` to
  `http://127.0.0.1:8002` (see `frontend/vite.config.ts`).
- **Frontend (build):** `npm run build` from `frontend/` — runs `tsc -b && vite build`, outputs straight
  into `backend/static/` so the FastAPI server can serve the built SPA directly from port 8002 with
  no Vite involved. Type-check only: `cd frontend && npx tsc --noEmit`. Unit tests: `npm test` (Vitest). Lint: `npm run lint` (ESLint 9,
  `frontend/eslint.config.js`; must stay at 0 errors — `any` and effect-dependency findings are warnings).
- **Docker:** `docker build -f deploy/Dockerfile .` from the repo root.
- **Local Postgres:** `docker compose -f deploy/docker-compose.postgres.yml up -d`, then set
  `DATABASE_URL` in `.env`.
- If plain `python` resolves to a broken Store stub or to `.venv-gpu` (which lacks the backend's packages), use the
  real interpreter, e.g. `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` (`deploy/start-all.ps1` picks it the same way).
- **Lint (dev tools: `pip install -r backend/requirements-dev.txt`):** `python -m ruff check backend` (config
  `ruff.toml`, must stay clean); dead code: `python -m vulture backend --min-confidence 80 --exclude backend/static`.
- **Tests (local only, `tests/` is gitignored, never push it):** `python -m pytest -q tests/<area>`; one test:
  `python -m pytest -q tests/dataset/test_x.py::test_name`. `tests/conftest.py` holds the shared fixtures.
- **Clear stale bytecode** (uvicorn `--reload` sometimes misses changes):
  `Get-ChildItem -Path "backend" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force`

## Architecture

### Backend layout (FastAPI, Django-style feature folders)

```
backend/
  main.py              FastAPI app: mounts domains router, /api/auth, /ws, serves SPA
  core/                shared infra — config.py (DATA_DIR/UPLOAD_DIR/EXPORT_DIR), events.py
                       (WebSocket broadcast), db.py (_conn, schema bootstrap, MIGRATIONS), pg.py
                       (sqlite3-like Postgres adapter), store.py (facade that re-exports core.db and every
                       domain repository), LLM clients (llm_provider.py & co.)
  domains/<stage>/     router.py (APIRouter, bare sub-paths) · schemas.py (Pydantic) ·
                       repository.py (SQL via core.db._conn) · service modules (service.py, …)
  agents/              LLM agents
```

Rules: services call persistence through `from ...core import store` (add new SQL functions to
the owning `domains/<stage>/repository.py`, never to `store.py`); repositories import `_conn` from
`core.db` (domains already moved to SQLAlchemy — billing, guardrails, exclusions, assets, memory, datasources, providers, usage, auth, plan, brief, qc, deckstudio, agent — use `core/sa.begin()` + their `models.py`
instead; see the database bullet below); build file paths from `core.config` constants, never from `Path(__file__)`; services
never import a `router.py`. Frontend (`frontend/src/`): `pages/` · `components/` · `context/`
(React providers) · `hooks/` · `services/` (REST + WebSocket clients) · `types/` · `data/` (demo fixtures).

- **Backend:** Python FastAPI (`backend/main.py`), single process; background work runs on the
  shared job runner in `core/jobs.py`.
- **Frontend:** React 18 + TypeScript + Vite 5 + Tailwind CSS 4 (`frontend/src/`). The page is
  chosen by a `useState<Page>` in `App.tsx`, mirrored into the URL path. Page components in
  `frontend/src/pages/`, one per pipeline stage, QC step or settings tab.
- **Database:** Postgres only, one database: local Docker Postgres or Render
  Postgres in production, via `DATABASE_URL` (required — the server refuses to start without it).
  Repositories write SQLite-style SQL (`?` placeholders; `INSERT OR IGNORE` is NOT translated, use `ON CONFLICT DO NOTHING`), which `core/pg.py`
  translates; there is no SQLite fallback. Older docs describing `intelligence.db` or
  `data/memory.db` are out of date (`config.MEMORY_DB_PATH` survives only because `core/db.py` hashes it into the schema name). Every table (projects/specs/strategies/jobs/deliverables/QC,
  plus the unused legacy tables of the deleted products) lives there.
  **Moving to SQLAlchemy, one domain at a time:** `core/sa.py` (pooled engine, capped connections) +
  `domains/<stage>/models.py` (SQLAlchemy Core `Table`s) + Core queries in that domain's `repository.py`. Done:
  `billing`, `guardrails`, `exclusions`, `assets` (intel_assets), `memory`, `datasources`, `providers`, `usage`, `auth`, `plan`, `brief`, `qc`, `deckstudio` (reference library), `agent`. A repository that `core/store.py`
  star-imports must declare `__all__` (or SQLAlchemy names leak into `store`). New code in a moved domain never uses `_conn`/`pg.py`; tables are still created by `core/db.py`
  MIGRATIONS until Alembic takes over with the first schema change in a moved domain.
  Uploaded dataset files are also kept in `intel_dataset_files`, since a hosted server's disk may
  not survive a restart.
- **S3 object store (optional):** `core/object_store.py` puts everything kept beyond the database under the
  `HunterAgent/` prefix of `AWS_S3_BUCKET` (keys `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`,
  `AWS_S3_BUCKET`; values are `.strip()`ped). Without the keys every call returns None and callers fall back to
  Postgres; failures log and never fail a deck or a tagging run. Finished decks (`deliverable/deck_store.py`) and
  the PPT reference decks live there; uploaded Data set files go under `datasets/project-{id}/`.
- **Asset library:** `domains/assets/` (`library.py` = table `intel_asset_library`, migration 35; `service.py` =
  fetchers) holds logos, site icons, flags and slide photos shared across organisations: bytes in S3, summary +
  embedding in Postgres, so a near-identical photo of the same subject and role is reused before any search.
  Embeddings come from `EMBEDDING_MODEL_API_KEY` / `EMBEDDING_MODEL_BASE_URL` / `EMBEDDING_MODEL_NAME` (falling
  back to the `NVIDIA_EMBED_*` keys).
- **Data set domain:** `domains/dataset/` is the new upload → tag → review flow (`DataSet.tsx`): project-wide
  `intel_articles` (deduped on normalised URL), one `intel_article_rq` row per article per approved RQ, and the
  tagging job (`tagging_job.py`: content → article tags → themes → RQs → relations). The deck reads only approved
  rows, through `deliverable/rows.approved_rows`. Analyst decisions are final: a Re-tag never overwrites a decided row.
- **LLM chain:** `backend/core/llm_provider.py::build_llm_client()` is the single factory
  used everywhere a chat/embedding client is needed (`get_llm_client()` in the same module,
  and every other call site — `domains/plan/service.py`,
  `core/llm_synthesis.py`, the `agents/*.py` modules). All clients live in `core/`. It returns a
  `HybridLLMClient` with no cross-provider fallback on either side:
  - **Chat:** the platform's Azure OpenAI (`azure_openai_client.py`, `AZURE_OPENAI_*` env vars), unless the
    scoped organisation has its own default provider (Settings → LLM Providers, `domains/providers/`,
    clients in `core/org_chat_clients.py`: OpenAI-compatible, Azure OpenAI, Anthropic, Gemini). The org comes
    from the usage scope (the project's org, else the session's active org); an org's models fail over in order
    (saved default, then newest first; `providers/service.call`), wait and resume when all are down
    (`providers/outage.py` emails the org's admins) and never fall back to the platform. Keys are Fernet-encrypted (`core/secret_box.py`,
    `PROVIDER_SECRET_KEY`). `chat()` raises `NoChatProviderError` if nothing is configured.
  - **Embeddings:** NVIDIA NIM only (`nvidia_embed_client.py`, `NVIDIA_EMBED_*` env vars).
    `embed()`/`embed_batch()` raise `NoEmbedProviderError` if unconfigured or unreachable.
  - Every LLM-dependent feature in the Intelligence Platform still has its own
    deterministic/rule-based tier beneath this — the deterministic tier is not a stub, it
    produces real content.
- **Emails:** one layout for every email (`core/email_layout.py`, `core/templates/email.html.j2`); project
  emails in `deliverable/notify.py`, account emails in `auth/recovery.py`, outage emails in `providers/outage.py`.
- **Communication:** REST (`/api/intel/*`, `/api/auth/*`) + a single shared WebSocket (`/ws`) broadcasting job/run progress to all clients.
- **Brand colors:** Violet `#5B2C9D` (primary), QC teal `#0F7B6C`.

### Intelligence Platform stage → module map

Each stage is a `domains/<stage>/` folder + one or more frontend pages (paths below are relative
to `backend/domains/` unless they start with `agents/`). Consult
`docs/CURRENT_STATUS.md` for exhaustive per-stage detail (DB tables, endpoint counts, test
counts) before assuming a stage is unbuilt — most of the pipeline is fully implemented and tested,
not scaffolding.

| Stage | Backend | Frontend |
|---|---|---|
| Projects & jobs | `projects/` | `LandingPage.tsx`, `Dashboard.tsx` |
| Brief & Scope | `brief/parser.py`, `agents/brief_scope.py`, `spec/service.py`, `spec/renderer.py` | `NewProject.tsx`, `BriefScopeReview.tsx` |
| Background Research | `research/service.py`, `research/web_research.py`, `research/news_search.py`, `agents/brand_intelligence.py` | `BackgroundResearch.tsx` |
| Search Strategy + dataset evaluation | `strategy/router.py` (`_build_deterministic_strategy()`), `agents/meltwater_query_builder.py`, `agents/query_evaluator.py` | `SearchStrategy.tsx`, `QueryEvaluation.tsx` |
| Matching label + Data set | `dataset/` (router, service, tagging_job, batching, repository) plus the RQ routes in `strategy/router.py`, `agents/article_tagging.py`, `agents/rq_tagging.py` | `MatchingLabel.tsx`, `DataSet.tsx` (+ `components/dataset/`); `data-sources` URLs alias `data-set` |
| Research Plan | `plan/service.py`; `execution/service.py` holds only the dataset loaders used by `deliverable/` and `strategy/` | `ResearchPlan.tsx` |
| Deliverables (deck engine) | `deliverable/`, `deckstudio/` | `DeliverablesPage.tsx` |
| QC flow (separate from the pipeline) | `qc/parser.py`, `qc/service.py`, `qc/export.py`, `qc/source_retrieval.py` | `QCUpload.tsx` → `QCFieldMapping.tsx` → `QCResults.tsx` → `QCExport.tsx` |

Note: `ResearchPlan` and `QueryEvaluation` are registered in `App.tsx`'s `PAGES`, so they open by
URL (e.g. `/{projectId}/research-plan`), but no sidebar or Dashboard link leads to them.

## Critical Patterns

- **LLM fallback chain:** implemented via `_get_llm()` in `domains/research/service.py` and
  `get_llm_client()` (`core/llm_provider.py`, used by the research/strategy/spec routers). In
  `compose_brief()`, `llm_succeeded` is set only when map-reduce summarization *actually* returned
  sections (vs. an exception being caught and rule-based fallback substituted). This drives the
  `enrichment_status` field (`"llm_synthesized"` vs `"rule_based"`) — never infer LLM success from
  whether a client object is truthy.
- **Competitor extraction shares one pattern list.** Natural-language brief text is parsed with
  `COMPETITOR_PATTERNS` / `competitors_from_text()` in `domains/research/web_research.py`, used by
  `domains/research/service.py` (`_extract_competitors`), `web_research.py` (`_extract_competitors`)
  and `domains/strategy/router.py` (`_extract_competitors_from_text`, which keeps its own
  all-matches parse). Change the patterns there only.
- **Strategy generation always resolves to deterministic.** In `domains/strategy/router.py`, four
  failure paths (no LLM reachable, LLM timeout, LLM exception, empty LLM result) all funnel into
  `_build_deterministic_strategy(spec, raw_brief_text)` rather than returning an error — a failed
  LLM call must never surface as "generation failed" in the UI.
- **LLM call timeouts are expected, not exceptional.** Background research and strategy generation
  use `concurrent.futures` with timeouts and `pool.shutdown(wait=False)` to abandon a slow/stuck
  Azure OpenAI call; results are persisted *before* the LLM enrichment step so a timeout doesn't
  lose already-fetched web research.
- **`__pycache__` can mask code changes**, especially with uvicorn `--reload`. If an edit doesn't
  seem to take effect, clear it and restart without `--reload` (see Quick Start).
- **Agentic memory sits under every GPT call** (`domains/memory/service.py`, table `memory_items`).
  `HybridLLMClient.chat()` answers an identical prompt from memory for 7 days (a repeat on the same client
  is a retry and goes to GPT). Brief & Scope gets the org's known brand facts and procedural lessons, and
  reuses the org's web grounding for 14 days; validation failures in brief_scope, research_planner and
  the query builder become lessons. Any user-triggered "Regenerate"/"Reanalyze" must run inside
  `memory.fresh()` (inside the worker thread — contextvars don't cross threads) or it gets the old answer back.
## Known Issues

- **`ANTHROPIC_API_KEY` has no effect** — Claude is reachable only as an organisation's own provider
  (see LLM chain above). Check `.env`'s `AZURE_OPENAI_*` keys before assuming LLM
  synthesis is live; if Azure is unconfigured/unreachable, every LLM-dependent feature falls
  straight to its deterministic/rule-based tier.
- **JBL vs Jabil entity confusion** — research results can include Jabil Inc. (ticker "JBL") or the
  WWE commentator "JBL" instead of the intended speaker/brand; entity disambiguation in
  `domains/research/web_research.py` is incomplete.
- **Hand-rolled URL routing, on purpose** — URL <-> page mapping lives in `frontend/src/routing.ts` (unit-tested:
  `npm test`), history handling in `App.tsx`. React Router was evaluated and NOT adopted (log 2026-11-12-12): the
  async project hydration, stage gating and push-after-project-switch logic stay custom either way, and Router's
  location-on-every-navigate would re-trigger project hydration with the previous project's id mid-switch.
- **No Meltwater API integration** — Boolean search queries are validated for syntax only, never
  tested against Meltwater's actual parser.

## Handover & Status Docs

- `docs/handover/HANDOVER.md` — architecture, bug history, environment variables, DB schema reference.
- `docs/CURRENT_STATUS.md` — authoritative per-stage completion status, endpoint/table/test counts,
  sprint-by-sprint change log. Check this before assuming a stage is unbuilt.
- `docs/PRODUCT_SPEC.md` — product spec. (`docs/PRESENTATION_COMPOSER.md`, `POWERPOINT_RENDERER.md`,
  `WORD_RENDERER.md`, `PUBLISHING_GATEWAY.md`, `SLIDE_INTELLIGENCE_GUIDE.md` describe deleted code.)
