# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Two products live in one app:

1. **Brief-to-Deck agent** (the original tool, see `README.md`) — watches a folder for client
   briefs, retrieves matching slides from an indexed historical deck library, drafts missing
   content, and assembles a branded PowerPoint via Windows COM automation.
   Lives in `agent/app/deck/`: `pipeline.py`, `deck_builder.py`, `deck_index.py`, `retrieval.py`,
   `slide_copy_com.py`, `chart_builders.py`, `watcher.py`, `memory.py` → `agent/data/memory.db`.
2. **Hunter Intelligence Platform** (the actively developed product, see
   `docs/CURRENT_STATUS.md` and `handover/HANDOVER.md`) — a 15-stage research pipeline (brief →
   scope → background research → search strategy → data sources → research execution → evidence
   library → insights → storyline → slide intelligence → presentation composer → PPTX/Word
   renderers → publishing gateway) plus a separate **QC flow** for cleaning Meltwater/Empower
   Excel exports. Lives in `agent/app/domains/<stage>/` (one folder per stage, see Backend layout
   below); `domains/__init__.py` mounts every stage router under `/api/intel`.

Both are mounted on the same FastAPI app (`agent/app/main.py`) and the same React SPA. When
orienting in this codebase, first figure out which of the two systems a file belongs to — they
share LLM clients and some helper patterns but have separate databases, separate pipelines, and
mostly disjoint code paths.

## Quick Start

- **Backend:** `python -m uvicorn agent.app.main:app --host 0.0.0.0 --port 8002` from the project root
  (or `.\start.ps1` to launch backend + frontend together).
- **Frontend (dev):** `npm run dev` from `web/` — Vite on port 5173, proxies `/api` and `/ws` to
  `http://127.0.0.1:8002` (see `web/vite.config.ts`).
- **Frontend (build):** `npm run build` from `web/` — runs `tsc -b && vite build`, outputs straight
  into `agent/static/` so the FastAPI server can serve the built SPA directly from port 8002 with
  no Vite involved.
- If plain `python`/`pip` resolve to a broken Microsoft Store stub on a given machine, use the full
  path to the real interpreter instead — check with `where python3`.
- **Kill stale backend processes:** `Get-Process -Name python,python3 -ErrorAction SilentlyContinue | Stop-Process -Force`
- **Clear stale bytecode** (uvicorn `--reload` sometimes misses changes):
  `Get-ChildItem -Path "agent\app" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force`

### Tests

```powershell
# Unit tests (agent/tests/, ~17 files)
python -m pytest agent/tests/ -x -q --ignore=agent/tests/test_e2e_live_workflow.py

# Single test file / test
python -m pytest agent/tests/test_intelligence_store.py -v
python -m pytest agent/tests/test_executor_service.py::TestClassName::test_name -v

# E2E test — requires a running server (port 8000 in the test, adjust if yours runs on 8002)
python -u agent/tests/test_e2e_live_workflow.py

# Frontend type-check (no separate lint/test script configured)
cd web && npx tsc --noEmit
```

## Architecture

### Backend layout (FastAPI, Django-style feature folders)

```
agent/app/
  main.py              FastAPI app: mounts domains router, /ws, Brief-to-Deck REST, serves SPA
  core/                shared infra — config.py (DATA_DIR/UPLOAD_DIR/EXPORT_DIR), db.py (_conn,
                       schema bootstrap), events.py (WebSocket broadcast), store.py (facade that
                       re-exports every domain repository), LLM clients (llm_provider.py & co.)
  domains/<stage>/     router.py (APIRouter, bare sub-paths) · schemas.py (Pydantic) ·
                       repository.py (SQLite) · service modules (service.py, renderer.py, …)
  deck/                Brief-to-Deck product
  agents/  methods/    LLM agents and pluggable deterministic analysis methods
```

Rules: services call persistence through `from ...core import store` (add new SQL functions to
the owning `domains/<stage>/repository.py`, never to `store.py`); build file paths from
`core.config` constants, never from `Path(__file__)`; services never import a `router.py`.
Frontend (`web/src/`): `pages/` · `components/` · `context/` (React providers) · `hooks/` ·
`services/` (REST + WebSocket clients) · `types/` · `data/` (demo fixtures).

- **Backend:** Python FastAPI (`agent/app/main.py`), single process, single-threaded pipeline
  execution (`_run_lock` in `main.py` — only one Brief-to-Deck run at a time by design, since
  PowerPoint COM automation and the local LLM are both single-consumer on this machine).
- **Frontend:** React 18 + TypeScript + Vite 5 + Tailwind CSS 4 (`web/src/`). No router — `App.tsx`
  holds a `useState<Page>` and switches on it; there is no deep linking or browser back/forward.
  ~27 page components in `web/src/pages/`, one per pipeline stage or QC step.
- **Database:** despite the docs (`handover/HANDOVER.md`, `docs/CURRENT_STATUS.md`) describing
  two separate SQLite files, `deck/memory.py` and `core/db.py` both actually connect to the
  same `config.MEMORY_DB_PATH` (`agent/data/memory.db`) — verify with
  `grep sqlite3.connect agent/app/deck/memory.py agent/app/core/db.py` before trusting the
  "separate `intelligence.db`" claim in older docs. Both Brief-to-Deck tables (runs/events/chat/
  slide_index) and every Intelligence Platform table (projects/specs/strategies/jobs/evidence/
  insights/storylines/renders/QC, 58+ tables) live in this one file.
- **LLM chain:** `agent/app/core/llm_provider.py::build_llm_client(settings)` is the single factory
  used everywhere a chat/embedding client is needed (`get_llm_client()` in `core/anthropic_client.py`,
  and every other call site — `deck/pipeline.py`, `domains/plan/service.py`,
  `core/llm_synthesis.py`, the `agents/*.py` modules). All clients live in `core/`. It returns a
  `HybridLLMClient` with no cross-provider fallback on either side:
  - **Chat:** Azure OpenAI only (`azure_openai_client.py`, `AZURE_OPENAI_*` env vars). `chat()`
    raises `NoChatProviderError` if unconfigured or unreachable.
  - **Embeddings:** NVIDIA NIM only (`nvidia_embed_client.py`, `NVIDIA_EMBED_*` env vars).
    `embed()`/`embed_batch()` raise `NoEmbedProviderError` if unconfigured or unreachable.
  - Every LLM-dependent feature in the Intelligence Platform still has its own
    deterministic/rule-based tier beneath this — the deterministic tier is not a stub, it
    produces real content.
- **Communication:** REST (`/api/*` for Brief-to-Deck, `/api/intel/*` for the Intelligence
  Platform) + a single shared WebSocket (`/ws`) broadcasting job/run progress to all clients.
- **Brand colors:** Violet `#5B2C9D` (primary), QC teal `#0F7B6C`.

### Intelligence Platform stage → module map

Each stage is a `domains/<stage>/` folder + one or more frontend pages (paths below are relative
to `agent/app/domains/` unless they start with `agents/` or `methods/`). Consult
`docs/CURRENT_STATUS.md` for exhaustive per-stage detail (DB tables, endpoint counts, test
counts) before assuming a stage is unbuilt — most of the pipeline is fully implemented and tested,
not scaffolding.

| Stage | Backend | Frontend |
|---|---|---|
| Projects & jobs | `projects/` | `LandingPage.tsx`, `Dashboard.tsx` |
| Brief & Scope | `brief/parser.py`, `agents/brief_scope.py`, `spec/service.py`, `spec/renderer.py` | `NewProject.tsx`, `BriefScopeReview.tsx` |
| Background Research | `research/service.py`, `research/web_research.py`, `research/news_search.py`, `agents/brand_intelligence.py` | `BackgroundResearch.tsx` |
| Search Strategy + dataset evaluation | `strategy/router.py` (`_build_deterministic_strategy()`), `agents/meltwater_query_builder.py`, `agents/query_evaluator.py` | `SearchStrategy.tsx`, `QueryEvaluation.tsx` |
| Research Plan / Execution | `plan/service.py`, `execution/service.py`, `methods/` (12 pluggable deterministic analysis methods, decorator-registered) | `ResearchPlan.tsx`, `ResearchExecution.tsx` |
| Evidence Library | `library/service.py` | `EvidenceLibrary.tsx` |
| Analysis & Insights | `insights/service.py`, `insights/sov_analyzer.py`, `insights/theme_classifier.py` | `AnalysisPage.tsx`, `InsightsPage.tsx` |
| Storyline | `storyline/service.py` | `StorylinePage.tsx` |
| Slide Intelligence | `slides/extractor.py`, `slides/retrieval.py`, `slides/service.py` | `SlideIntelligencePage.tsx` |
| Presentation Composer | `composer/service.py` | `PresentationComposerPage.tsx` |
| PPTX / Word Renderers | `rendering/pptx.py`, `rendering/word.py` | `PowerPointRendererPage.tsx`, `WordRendererPage.tsx` |
| Publishing Gateway | `publishing/service.py` | `PublishingGatewayPage.tsx` |
| Pipeline Orchestrator (cross-stage) | `pipeline/service.py` — dependency graph, topological sort, caching, 5 execution modes | `PipelineOrchestratorPage.tsx` |
| QC flow (separate from the pipeline) | `qc/parser.py`, `qc/service.py`, `qc/export.py`, `qc/source_retrieval.py` | `QCUpload.tsx` → `QCFieldMapping.tsx` → `QCResults.tsx` → `QCExport.tsx` |

Note: 11 pages (`ResearchPlan`, `EvidenceLibrary`, `InsightsPage`, `StorylinePage`,
`SlideIntelligencePage`, `PresentationComposerPage`, `PowerPointRendererPage`, `WordRendererPage`,
`PublishingGatewayPage`, `PipelineOrchestratorPage`, `QueryEvaluation`) and 4 components
(`LiveFeed`, `RunStatus`, `SettingsPanel`, `TopHeader`) exist but are not rendered from `App.tsx`.

## Critical Patterns

- **LLM fallback chain:** implemented via `_get_llm()` in `domains/research/service.py` and
  `get_llm_client()` (`core/anthropic_client.py`, used by the research/strategy/spec routers). `_compose_with_llm()` returns `(sections, bool)` —
  the bool tracks whether the LLM *actually* produced the content (vs. an exception being caught
  and rule-based fallback silently substituted). This drives the `enrichment_status` field
  (`"llm_synthesized"` vs `"web_only"` vs `"rule_based"`) — never infer LLM success from whether a
  client object is truthy.
- **Competitor extraction stays in sync across three files.** Natural-language brief text is
  parsed with multiple regex patterns duplicated in `domains/strategy/router.py`
  (`_extract_competitors_from_text`), `domains/research/service.py` (`_extract_competitors`), and
  `domains/research/web_research.py` (`_extract_competitors`). Changing one without the other two
  reintroduces the bug this was built to fix.
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
- **Only one Brief-to-Deck run executes at a time** (`_run_lock` / `_run_busy` in `main.py`) — a
  second trigger while busy broadcasts `run_queued_conflict` instead of queuing.

## Known Issues

- **Anthropic is unused** — the chat chain is Azure OpenAI only (see LLM chain above);
  `ANTHROPIC_API_KEY` has no effect. Check `.env`'s `AZURE_OPENAI_*` keys before assuming LLM
  synthesis is live; if Azure is unconfigured/unreachable, every LLM-dependent feature falls
  straight to its deterministic/rule-based tier.
- **JBL vs Jabil entity confusion** — research results can include Jabil Inc. (ticker "JBL") or the
  WWE commentator "JBL" instead of the intended speaker/brand; entity disambiguation in
  `domains/research/web_research.py` is incomplete.
- **No URL routing** in the frontend — state-based page switching only, no deep linking or
  browser back/forward.
- **Slide Intelligence classification is keyword-based**, not LLM-based — nuanced slide purposes
  can be misclassified (manual correction workflow exists to compensate).
- **No Meltwater API integration** — Boolean search queries are validated for syntax only, never
  tested against Meltwater's actual parser.

## Handover & Status Docs

- `handover/HANDOVER.md` — architecture, bug history, environment variables, DB schema reference.
- `docs/CURRENT_STATUS.md` — authoritative per-stage completion status, endpoint/table/test counts,
  sprint-by-sprint change log. Check this before assuming a stage is unbuilt.
- `docs/PRODUCT_SPEC.md`, `docs/PIPELINE_ORCHESTRATOR.md`, `docs/PRESENTATION_COMPOSER.md`,
  `docs/POWERPOINT_RENDERER.md`, `docs/WORD_RENDERER.md`, `docs/PUBLISHING_GATEWAY.md`,
  `docs/SLIDE_INTELLIGENCE_GUIDE.md` — per-subsystem deep dives.
