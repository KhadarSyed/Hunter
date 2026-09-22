# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Two products live in one app:

1. **Brief-to-Deck agent** (the original tool, see `README.md`) — watches a folder for client
   briefs, retrieves matching slides from an indexed historical deck library, drafts missing
   content, and assembles a branded PowerPoint via Windows COM automation.
   Entry points: `pipeline.py`, `deck_builder.py`, `deck_index.py`, `retrieval.py`,
   `slide_copy_com.py`, `chart_builders.py`, `watcher.py`, `memory.py` → `agent/data/memory.db`.
2. **Hunter Intelligence Platform** (the actively developed product, see
   `docs/CURRENT_STATUS.md` and `handover/HANDOVER.md`) — a 15-stage research pipeline (brief →
   scope → background research → search strategy → data sources → research execution → evidence
   library → insights → storyline → slide intelligence → presentation composer → PPTX/Word
   renderers → publishing gateway) plus a separate **QC flow** for cleaning Meltwater/Empower
   Excel exports. Entry points: `intelligence_api.py` (~3,400 lines, all `/api/intel/*` routes),
   `intelligence_store.py` (~6,100 lines, SQLite layer, 58+ tables in `agent/data/intelligence.db`),
   and one service module per stage (see Architecture below).

Both are mounted on the same FastAPI app (`agent/app/main.py`) and the same React SPA. When
orienting in this codebase, first figure out which of the two systems a file belongs to — they
share LLM clients and some helper patterns but have separate databases, separate pipelines, and
mostly disjoint code paths.

## Quick Start

- **Backend:** `python -m uvicorn agent.app.main:app --host 0.0.0.0 --port 8002` from the project root
  (or `.\start.ps1` to launch backend + frontend + Ollama together).
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

- **Backend:** Python FastAPI (`agent/app/main.py`), single process, single-threaded pipeline
  execution (`_run_lock` in `main.py` — only one Brief-to-Deck run at a time by design, since
  PowerPoint COM automation and the local LLM are both single-consumer on this machine).
- **Frontend:** React 18 + TypeScript + Vite 5 + Tailwind CSS 4 (`web/src/`). No router — `App.tsx`
  holds a `useState<Page>` and switches on it; there is no deep linking or browser back/forward.
  ~27 page components in `web/src/pages/`, one per pipeline stage or QC step.
- **Database:** despite the docs (`handover/HANDOVER.md`, `docs/CURRENT_STATUS.md`) describing
  two separate SQLite files, `memory.py` and `intelligence_store.py` both actually connect to the
  same `config.MEMORY_DB_PATH` (`agent/data/memory.db`) — verify with
  `grep sqlite3.connect agent/app/memory.py agent/app/intelligence_store.py` before trusting the
  "separate `intelligence.db`" claim in older docs. Both Brief-to-Deck tables (runs/events/chat/
  slide_index) and every Intelligence Platform table (projects/specs/strategies/jobs/evidence/
  insights/storylines/renders/QC, 58+ tables) live in this one file.
- **LLM chain:** `agent/app/llm_provider.py::build_llm_client(settings)` is the single factory
  used everywhere a chat/embedding client is needed (`get_llm_client()` in `anthropic_client.py`,
  and the former direct `OllamaClient(...)` construction sites in `pipeline.py`, `main.py`,
  `planner_service.py`, `llm_synthesis.py`). It returns a `HybridLLMClient` that routes:
  - **Chat:** Azure OpenAI (`azure_openai_client.py`, `AZURE_OPENAI_*` env vars) → Anthropic
    (`anthropic_client.py`, `ANTHROPIC_API_KEY`) → local Ollama (`ollama_client.py`, `qwen2.5:3b`).
  - **Embeddings:** NVIDIA NIM (`nvidia_embed_client.py`, `NVIDIA_EMBED_*` env vars) → local
    Ollama (`nomic-embed-text`).
  - A cloud provider that raises at call time falls back to Ollama automatically (see
    `HybridLLMClient.chat`/`.embed` try/except). Below that, every LLM-dependent feature in the
    Intelligence Platform still has its own deterministic/rule-based tier — the deterministic
    tier is not a stub, it produces real content. `/api/status`'s `ollama_reachable` field is the
    one intentional exception left on raw `OllamaClient` — it reports real local-Ollama health,
    not overall LLM availability.
- **Communication:** REST (`/api/*` for Brief-to-Deck, `/api/intel/*` for the Intelligence
  Platform) + a single shared WebSocket (`/ws`) broadcasting job/run progress to all clients.
- **Brand colors:** Violet `#5B2C9D` (primary), QC teal `#0F7B6C`.

### Intelligence Platform stage → module map

Each stage is a backend service module + one or more frontend pages. Consult
`docs/CURRENT_STATUS.md` for exhaustive per-stage detail (DB tables, endpoint counts, test
counts) before assuming a stage is unbuilt — most of the pipeline is fully implemented and tested,
not scaffolding.

| Stage | Backend | Frontend |
|---|---|---|
| Brief & Scope | `brief_parser.py`, `agents/brief_scope.py`, `research_spec_service.py` | `NewProject.tsx`, `BriefScopeReview.tsx` |
| Background Research | `background_brief_service.py`, `web_research_adapter.py`, `agents/brand_intelligence.py` | `BackgroundResearch.tsx` |
| Search Strategy | `agents/meltwater_query_builder.py`, `_build_deterministic_strategy()` in `intelligence_api.py` | `SearchStrategy.tsx` |
| Query Evaluation | `agents/query_evaluator.py` | `QueryEvaluation.tsx` |
| Research Plan / Execution | `planner_service.py`, `executor_service.py`, `methods/` (12 pluggable deterministic analysis methods, decorator-registered) | `ResearchPlan.tsx`, `ResearchExecution.tsx` |
| Evidence Library | `evidence_library.py` | `EvidenceLibrary.tsx` |
| Analysis & Insights | `insight_generator.py`, `sov_analyzer.py`, `theme_classifier.py` | `AnalysisPage.tsx`, `InsightsPage.tsx` |
| Storyline | `storyline_builder.py` | `StorylinePage.tsx` |
| Slide Intelligence | `slide_extractor.py`, `slide_retrieval.py`, `slide_intelligence.py` | `SlideIntelligencePage.tsx` |
| Presentation Composer | `presentation_composer.py` | `PresentationComposerPage.tsx` |
| PPTX / Word Renderers | `pptx_renderer.py`, `word_renderer.py` | `PowerPointRendererPage.tsx`, `WordRendererPage.tsx` |
| Publishing Gateway | `publishing_gateway.py` | `PublishingGatewayPage.tsx` |
| Pipeline Orchestrator (cross-stage) | `pipeline_orchestrator.py` — dependency graph, topological sort, caching, 5 execution modes | `PipelineOrchestratorPage.tsx` |
| QC flow (separate from the pipeline) | `qc_parser.py`, `qc_service.py`, `qc_export.py` | `QCUpload.tsx` → `QCFieldMapping.tsx` → `QCResults.tsx` → `QCExport.tsx` |

## Critical Patterns

- **LLM fallback chain:** implemented via `_get_llm()` in `background_brief_service.py` and
  `get_llm_client()` in `intelligence_api.py`. `_compose_with_llm()` returns `(sections, bool)` —
  the bool tracks whether the LLM *actually* produced the content (vs. an exception being caught
  and rule-based fallback silently substituted). This drives the `enrichment_status` field
  (`"llm_synthesized"` vs `"web_only"` vs `"rule_based"`) — never infer LLM success from whether a
  client object is truthy.
- **Competitor extraction stays in sync across three files.** Natural-language brief text is
  parsed with multiple regex patterns duplicated in `intelligence_api.py`
  (`_extract_competitors_from_text`), `background_brief_service.py` (`_extract_competitors`), and
  `web_research_adapter.py` (`_extract_competitors`). Changing one without the other two
  reintroduces the bug this was built to fix.
- **Strategy generation always resolves to deterministic.** In `intelligence_api.py`, four
  failure paths (no LLM reachable, LLM timeout, LLM exception, empty LLM result) all funnel into
  `_build_deterministic_strategy(spec, raw_brief_text)` rather than returning an error — a failed
  LLM call must never surface as "generation failed" in the UI.
- **CPU-only LLM inference means timeouts are expected, not exceptional.** Background research and
  strategy generation use `concurrent.futures` with timeouts and `pool.shutdown(wait=False)` to
  abandon blocking Ollama calls; results are persisted *before* the LLM enrichment step so a
  timeout doesn't lose already-fetched web research.
- **`__pycache__` can mask code changes**, especially with uvicorn `--reload`. If an edit doesn't
  seem to take effect, clear it and restart without `--reload` (see Quick Start).
- **Only one Brief-to-Deck run executes at a time** (`_run_lock` / `_run_busy` in `main.py`) — a
  second trigger while busy broadcasts `run_queued_conflict` instead of queuing.

## Known Issues

- **Anthropic API credits exhausted** — all LLM features currently fall through to Ollama (slow)
  or deterministic. Check `.env`'s `ANTHROPIC_API_KEY` before assuming Claude synthesis is live.
- **JBL vs Jabil entity confusion** — research results can include Jabil Inc. (ticker "JBL") or the
  WWE commentator "JBL" instead of the intended speaker/brand; entity disambiguation in
  `web_research_adapter.py` is incomplete.
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
