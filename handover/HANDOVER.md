# Hunter Intelligence Platform — Handover Document

**Last updated:** 2026-09-08
**Handed over by:** Sweta Shah (tonoy.barman@infovision.com)
**Project root:** `c:\Users\sweta.shah\Downloads\Sweta Claude Code`

---

## 1. What This Project Is

Hunter is a locally-hosted intelligence platform that takes a client brief (e.g. "Research JBL's competitive position in consumer audio"), runs a 13-stage pipeline of research → analysis → composition, and produces branded deliverables (PowerPoint decks, Word documents). It's built for InfoVision's consulting workflow.

**Two project types exist:**
- **Research projects** — Full 13-stage pipeline from brief to final deliverables
- **Monitoring QC projects** — Upload Meltwater/Empower Excel exports, run quality-control checks, export cleaned data

---

## 2. Tech Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| **Frontend** | React 18 + TypeScript + Vite 5 + Tailwind CSS 4 | SPA with state-based routing (no React Router) |
| **Backend** | Python FastAPI + uvicorn | REST API + WebSocket for real-time events |
| **Database** | SQLite (two files) | `agent/data/memory.db` (runs/chat), `agent/data/intelligence.db` (projects/specs/strategies) |
| **LLM — Primary** | Anthropic Claude API | Via `agent/app/anthropic_client.py`. **Credits are currently exhausted.** |
| **LLM — Fallback** | Ollama (local) | `qwen2.5:3b` for chat, `nomic-embed-text` for embeddings. CPU-only (i7-10510U), very slow. |
| **LLM — Last resort** | Deterministic/rule-based | Every LLM-dependent feature has a rule-based fallback that works without any LLM. |

**Brand colors:** Primary violet `#5B2C9D`, QC accent teal `#0F7B6C`

---

## 3. How To Run

### Prerequisites
- Python 3.11+ (currently at `C:\Users\sweta.shah\AppData\Local\Python\bin\python3.exe`)
- Node.js 18+ with npm
- Ollama installed locally (optional — for local LLM, runs on port 11434)

### Start Backend (port 8002)
```powershell
cd "c:\Users\sweta.shah\Downloads\Sweta Claude Code"

# Kill any stale Python processes first
Get-Process -Name python,python3 -ErrorAction SilentlyContinue | Stop-Process -Force

# Clear __pycache__ if code changes aren't taking effect
Get-ChildItem -Path "agent\app" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# Start
C:\Users\sweta.shah\AppData\Local\Python\bin\python3.exe -m uvicorn agent.app.main:app --host 0.0.0.0 --port 8002
```

### Start Frontend (port 5173)
```powershell
cd "c:\Users\sweta.shah\Downloads\Sweta Claude Code\web"
npm run dev
```

### Access
- **Frontend dev server:** http://localhost:5173 (proxies API calls to 8002)
- **Backend direct:** http://localhost:8002 (also serves built frontend from `agent/static/`)
- **WebSocket:** ws://localhost:8002/ws (real-time event feed)

### Common Issues
- **Port 8002 occupied:** Kill stale `python3` processes with `Get-Process -Name python,python3 | Stop-Process -Force`
- **Code changes not taking effect:** uvicorn's `--reload` flag sometimes misses changes. Kill all Python, clear `__pycache__`, restart without `--reload`.
- **"Failed to fetch" on Brief & Scope page:** Usually Ollama/Anthropic timeout, not a network issue. The Analyze Brief button calls LLM with a long timeout.

---

## 4. Architecture — The 13-Stage Pipeline

Each stage is a backend module + a frontend page. Stages run sequentially per project.

| # | Stage | Backend Module | Frontend Page | Status |
|---|-------|---------------|---------------|--------|
| 1 | **Brief & Scope** | `intelligence_api.py` (spec endpoints) + `brief_parser.py` | `NewProject.tsx` | Working — file upload, text paste, drag-drop |
| 2 | **Brief Scope Review** | `research_spec_service.py` + `agents/brief_scope.py` | `BriefScopeReview.tsx` | Working — LLM or rule-based spec generation |
| 3 | **Background Research** | `background_brief_service.py` + `web_research_adapter.py` | `BackgroundResearch.tsx` | Working — DuckDuckGo search, LLM or rule-based composition |
| 4 | **Search Strategy** | `intelligence_api.py` (`_build_deterministic_strategy`) + `agents/meltwater_query_builder.py` | `SearchStrategy.tsx` | Working — deterministic fallback just fixed |
| 5 | **Data Sources** | `intelligence_api.py` (data source endpoints) | `DataSources.tsx` | UI exists |
| 6 | **Research Execution** | `research.py` + `executor_service.py` | `ResearchExecution.tsx` | UI exists |
| 7 | **Evidence Library** | `evidence_library.py` | `EvidenceLibrary.tsx` | UI exists |
| 8 | **Analysis & Insights** | `insight_generator.py` + `sov_analyzer.py` + `theme_classifier.py` | `AnalysisPage.tsx` + `InsightsPage.tsx` | UI exists |
| 9 | **Storyline** | `storyline_builder.py` | `StorylinePage.tsx` | UI exists |
| 10 | **Slide Intelligence** | `slide_intelligence.py` | `SlideIntelligencePage.tsx` | UI exists |
| 11 | **Presentation Composer** | `presentation_composer.py` | `PresentationComposerPage.tsx` | UI exists |
| 12 | **PPTX Renderer** | `pptx_renderer.py` | `PowerPointRendererPage.tsx` | UI exists |
| 13 | **Word Renderer** | `word_renderer.py` | `WordRendererPage.tsx` | UI exists |

**Additional pages (not in the linear pipeline):**
- `QueryEvaluation.tsx` → `agents/query_evaluator.py`
- `PipelineOrchestratorPage.tsx` → `pipeline_orchestrator.py`
- `PublishingGatewayPage.tsx` → `publishing_gateway.py`
- QC flow: `QCUpload.tsx` → `QCFieldMapping.tsx` → `QCResults.tsx` → `QCExport.tsx` (uses `qc_service.py`, `qc_parser.py`, `qc_export.py`)

---

## 5. Key Files — Quick Reference

### Backend Core
| File | What it does |
|------|-------------|
| `agent/app/main.py` | FastAPI entrypoint, WebSocket manager, static SPA serving |
| `agent/app/intelligence_api.py` | **Main API router** — all `/api/intel/*` endpoints (~2800 lines). Strategy generation, brief parsing, project CRUD, job management |
| `agent/app/intelligence_store.py` | SQLite database layer for intelligence projects, specs, strategies, jobs |
| `agent/app/background_brief_service.py` | Brief composition engine — `compose_brief()`, rule-based builders, LLM synthesis |
| `agent/app/web_research_adapter.py` | Web research via DuckDuckGo — competitor extraction, entity search |
| `agent/app/ollama_client.py` | Ollama HTTP client (chat, embeddings, health check) |
| `agent/app/anthropic_client.py` | Anthropic Claude API client |
| `agent/app/config.py` | Settings dataclass, paths, load/save from `data/settings.json` |

### Frontend Core
| File | What it does |
|------|-------------|
| `web/src/App.tsx` | Root component, state-based page routing |
| `web/src/components/Sidebar.tsx` | Navigation sidebar with pipeline stages |
| `web/src/lib/intel-api.ts` | API client — all `fetch()` calls to backend |
| `web/src/lib/ws.ts` | WebSocket client for real-time events |
| `web/src/lib/project-context.tsx` | React context for active project state |
| `web/src/pages/NewProject.tsx` | Brief & Scope page — file upload, drag-drop, brief analysis |

### Agent Modules (LLM-powered)
| File | What it does |
|------|-------------|
| `agent/app/agents/brief_scope.py` | Spec generation from brief text (LLM prompt + validation) |
| `agent/app/agents/brand_intelligence.py` | Brand intelligence analysis agent |
| `agent/app/agents/meltwater_query_builder.py` | Meltwater Boolean query generation + `validate_boolean_syntax()` |
| `agent/app/agents/query_evaluator.py` | Query evaluation and scoring |
| `agent/app/agents/research_planner.py` | Research planning agent |

---

## 6. Critical Patterns & Design Decisions

### LLM Fallback Chain
Every LLM-dependent feature follows this pattern:
```
Anthropic API → Ollama (local) → Deterministic/rule-based
```
This is implemented via `_get_llm()` in `background_brief_service.py` and `get_llm_client()` in `intelligence_api.py`.

**Important:** Anthropic credits are exhausted. All features currently run on Ollama (slow, CPU-only) or fall through to deterministic. The deterministic fallbacks are NOT stubs — they produce real analytical content.

### `_compose_with_llm()` returns a tuple
```python
(sections_dict, llm_succeeded_bool)
```
The boolean tracks whether the LLM actually produced the content vs. the function catching an exception and returning rule-based fallback. This drives the `enrichment_status` field: `"llm_synthesized"` vs `"rule_based"`.

### Competitor Extraction — Multi-Pattern Regex
Competitors are extracted from natural-language brief text using multiple regex patterns in THREE files:
- `agent/app/intelligence_api.py` → `_extract_competitors_from_text()`
- `agent/app/background_brief_service.py` → `_extract_competitors()`
- `agent/app/web_research_adapter.py` → `_extract_competitors()`

All three must stay in sync. Patterns handle formats like:
- "The core competitive set includes Apple, Beats, Bose..."
- "Competitors: Apple, Beats, Bose"
- "Competitors are Apple, Beats, and Bose."

### Strategy Generation Fallback
In `intelligence_api.py`, the strategy generation endpoint has four fallback paths that all resolve to `_build_deterministic_strategy(spec, raw_brief_text)`:
1. No LLM reachable → deterministic
2. LLM timeout → deterministic
3. LLM exception → deterministic
4. LLM returns empty → deterministic

### Rule-Based Brief Builders
When LLM is unavailable, these functions in `background_brief_service.py` produce consulting-quality content:
- `_build_executive_summary_basic()` — Thematic analysis with competitive landscape and strategic implications
- `_build_brand_narrative_basic()` — Categorizes brand items into themes (Product & Innovation, Partnerships, Digital & Social, etc.)
- `_build_key_issues_basic()` — Structured sections: Reputation & Risk, Competitive Moves, Industry & Regulatory, Research Gaps

### WebSocket Event Broadcasting
Backend uses `_broadcast()` to push job updates to all connected WebSocket clients:
```python
_broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
            "progress_pct": 70, "message": "Building deterministic strategy"})
```
Frontend listens via `web/src/lib/ws.ts`.

---

## 7. Database Schema (Key Tables)

Both databases are SQLite. Schema is defined inline in `intelligence_store.py`.

### `agent/data/intelligence.db`
| Table | Purpose |
|-------|---------|
| `intel_projects` | Projects with `spec_json`, `project_type`, timestamps |
| `intel_research_specifications` | Versioned specs with `spec_json`, `raw_brief_text`, readiness status |
| `intel_spec_section_approvals` | Per-section approval tracking (draft/approved/locked) |
| `intel_spec_clarifications` | Clarification questions on specs |
| `intel_background_research` | Web research results, LLM output, enrichment status |
| `intel_search_strategies` | Meltwater Boolean strategies, versioned |
| `intel_strategy_query_versions` | Individual query versions within a strategy |
| `intel_jobs` | Async job tracking (status, progress, errors) |
| `intel_evidence_items` | Evidence library entries |
| `intel_insights` | Generated insights |
| `intel_storylines` | Narrative storylines |
| `intel_presentations` | Composed presentations |
| `intel_qc_*` | QC-related tables (uploads, mappings, results) |

### `agent/data/memory.db`
| Table | Purpose |
|-------|---------|
| `runs` | Pipeline execution runs |
| `events` | Pipeline events/logs |
| `chat_messages` | Chat history |
| `slide_index` | Indexed slide library for retrieval |

---

## 8. What Was Built & Fixed (Recent Session)

### Features Added
1. **File upload on Brief & Scope page** — `<input type="file">`, drag-drop handlers, backend `/api/intel/brief/parse-file` endpoint. Supports DOCX, PPTX, TXT, PDF, Excel.

2. **`parseBriefFile()` API client method** — in `web/src/lib/intel-api.ts`, sends FormData to backend.

### Bugs Fixed

| Bug | Root Cause | Fix Location |
|-----|-----------|-------------|
| Brand Narrative showing placeholder text | Anthropic API exhausted, `_compose_with_llm` exception handler referenced uninitialized `sections` variable | `background_brief_service.py` — exception handler returns `_compose_rule_based()` fallback cleanly |
| `enrichment_status` falsely showing "llm_synthesized" | Checked `if llm_client` (truthy) instead of whether LLM call succeeded | `background_brief_service.py` — `_compose_with_llm` now returns `(sections, bool)` tuple |
| Competitor extraction failing | Regex `r'[Cc]ompetitors?:\s*(.+?)(?:\n\|$)'` couldn't match "The core competitive set includes..." format | `background_brief_service.py`, `web_research_adapter.py`, `intelligence_api.py` — added multi-pattern regex |
| Executive summary too thin | Rule-based builder just listed headlines | `background_brief_service.py` — rewrote `_build_executive_summary_basic()` with thematic analysis |
| "Strategy Generation Failed" | Exception and empty-result paths returned error instead of falling back to deterministic | `intelligence_api.py` — all four paths now call `_build_deterministic_strategy()` |
| "No LLM reachable" fails hard | `return` statement killed the strategy job | `intelligence_api.py` — changed to `else` block, falls through to deterministic |
| `_build_deterministic_strategy` missed competitors | Only checked `validated_entities` and `scope.competitors` (empty when LLM didn't populate them) | `intelligence_api.py` — added `_extract_competitors_from_text()` fallback from raw brief |

---

## 9. Known Issues & Pending Work

### Must Fix
1. **JBL vs Jabil entity confusion** — Some research items are about Jabil Inc (stock ticker "JBL") and WWE commentator "JBL", not the speaker brand. Entity validation in `web_research_adapter.py` needs disambiguation logic.

2. **Anthropic API credits exhausted** — All LLM features fall back to Ollama (very slow, CPU-only) or deterministic. Either refill credits or add a new LLM provider.

### Should Verify
3. **Strategy generation on fresh projects** — The deterministic strategy fallback was tested on project 494 (JBL). Verify it works for new projects where the spec structure might differ.

4. **Background research re-run after competitor fix** — After fixing competitor extraction, project 494's research was re-run and competitors populated. But older projects may still have stale data.

### Nice To Have
5. **Pipeline stages 5-13** — Pages exist in the frontend but the full end-to-end flow (Data Sources → ... → Publishing) hasn't been tested as a complete pipeline run.

6. **Ollama model upgrade** — `qwen2.5:3b` is tiny and slow. If GPU becomes available, upgrade to a larger model.

7. **Search/routing** — Frontend uses state-based page switching (`useState<Page>`), not URL routing. Deep linking and browser back/forward don't work.

---

## 10. Environment Variables

**File:** `.env` at project root (loaded by `python-dotenv` in `main.py`)

| Variable | Purpose | Current State |
|----------|---------|--------------|
| `ANTHROPIC_API_KEY` | Anthropic Claude API | Set but **credits exhausted** |
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |

---

## 11. Project Structure Map

```
Sweta Claude Code/
├── .env                          # Environment variables
├── start.ps1                     # PowerShell launcher
├── Start Hunter Agent.bat        # Batch launcher
├── CLAUDE.md                     # Auto-loaded by Claude Code sessions
├── handover/
│   └── HANDOVER.md               # ← This document
│
├── agent/                        # Python backend
│   ├── requirements.txt          # Python dependencies
│   ├── app/
│   │   ├── main.py               # FastAPI entrypoint
│   │   ├── intelligence_api.py   # Main API router (~2800 lines)
│   │   ├── intelligence_store.py # SQLite database layer
│   │   ├── background_brief_service.py  # Brief composition engine
│   │   ├── web_research_adapter.py      # Web research + competitor extraction
│   │   ├── ollama_client.py      # Ollama LLM client
│   │   ├── anthropic_client.py   # Anthropic Claude client
│   │   ├── config.py             # Settings, paths
│   │   ├── brief_parser.py       # Parse uploaded brief files
│   │   ├── research.py           # Research execution
│   │   ├── research_spec_service.py     # Spec generation service
│   │   ├── evidence_library.py   # Evidence management
│   │   ├── insight_generator.py  # Insight generation
│   │   ├── storyline_builder.py  # Storyline composition
│   │   ├── presentation_composer.py     # Presentation assembly
│   │   ├── pptx_renderer.py      # PowerPoint rendering
│   │   ├── word_renderer.py      # Word document rendering
│   │   ├── pipeline_orchestrator.py     # Full pipeline orchestration
│   │   ├── publishing_gateway.py # Export/publishing
│   │   ├── sov_analyzer.py       # Share-of-voice analysis
│   │   ├── theme_classifier.py   # Theme classification
│   │   ├── qc_service.py         # QC service
│   │   ├── agents/
│   │   │   ├── brief_scope.py    # Brief → spec (LLM agent)
│   │   │   ├── brand_intelligence.py    # Brand analysis (LLM agent)
│   │   │   ├── meltwater_query_builder.py  # Boolean query gen (LLM agent)
│   │   │   ├── query_evaluator.py       # Query scoring (LLM agent)
│   │   │   └── research_planner.py      # Research planning (LLM agent)
│   │   └── methods/              # Method registry
│   ├── data/
│   │   ├── memory.db             # Main SQLite DB
│   │   ├── intelligence.db       # Intelligence project DB
│   │   ├── hunter_template.pptx  # PowerPoint template
│   │   ├── uploads/              # Uploaded files
│   │   ├── briefs/               # Generated briefs
│   │   └── rendered/             # Generated output documents
│   ├── static/                   # Built frontend (Vite output)
│   └── tests/                    # 17 test files
│
├── web/                          # React frontend
│   ├── package.json              # npm dependencies
│   ├── vite.config.ts            # Vite config (proxy to :8002)
│   ├── tsconfig.json             # TypeScript config
│   └── src/
│       ├── main.tsx              # React bootstrap
│       ├── App.tsx               # Root component, page routing
│       ├── pages/                # 27 page components
│       ├── components/           # 6 shared components
│       ├── lib/                  # 5 utility/API modules
│       └── data/                 # 4 type/demo data files
│
└── docs/                         # Feature documentation (8 .md files)
```

---

## 12. Testing

```powershell
# Run backend tests
cd "c:\Users\sweta.shah\Downloads\Sweta Claude Code"
C:\Users\sweta.shah\AppData\Local\Python\bin\python3.exe -m pytest agent/tests/ -v

# Type-check frontend
cd web
npx tsc --noEmit
```

Test files are in `agent/tests/` (17 files). They cover store operations, web research, query evaluation, pipeline orchestration, renderers, and the publishing gateway.

---

## 13. API Endpoints (Key Ones)

All prefixed with `/api/intel/`:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/projects` | List all projects |
| POST | `/projects` | Create project |
| GET | `/project/{id}` | Get project details |
| POST | `/brief/parse-file` | Upload and parse brief file |
| POST | `/spec/generate` | Generate research spec from brief |
| GET | `/spec/{project_id}` | Get latest spec |
| POST | `/research/background` | Run background research |
| GET | `/research/{project_id}` | Get research results |
| POST | `/strategy/generate` | Generate search strategy |
| GET | `/strategy/{project_id}` | Get strategy |
| GET | `/job/{job_id}` | Check async job status |
| GET | `/jobs/{project_id}` | List jobs for project |

---

*End of handover document. For questions, contact Sweta Shah.*
