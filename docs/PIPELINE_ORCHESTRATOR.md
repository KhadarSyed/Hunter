# Pipeline Orchestrator

Coordinates execution of the complete Hunter Intelligence 13-stage workflow from Brief & Scope through PowerPoint Renderer. Makes zero modifications to business logic in existing modules.

## Architecture

### Responsibilities

- Execution coordination and scheduling
- Dependency management (topological sort, parallel grouping)
- Caching with SHA-256 input hashing
- Incremental regeneration (changed-only mode)
- Failure recovery (skip downstream, preserve completed, retry)
- Progress tracking and performance monitoring

### Pipeline Stages

| # | Stage ID | Name | Dependencies | Approval Gate |
|---|----------|------|-------------|---------------|
| 1 | brief_scope | Brief & Scope | — | No |
| 2 | background_research | Background Research | brief_scope | Yes |
| 3 | search_strategy | Search Strategy | background_research | Yes |
| 4 | query_evaluation | Query Evaluation | search_strategy | No |
| 5 | dataset_upload | Dataset Upload | search_strategy | No |
| 6 | research_planner | Research Planner | background_research, search_strategy, dataset_upload | Yes |
| 7 | research_executor | Research Executor | research_planner | No |
| 8 | evidence_library | Evidence Library | research_executor | No |
| 9 | insight_generator | Insight Generator | evidence_library | Yes |
| 10 | storyline_builder | Storyline Builder | insight_generator | Yes |
| 11 | si_retrieval | SI Retrieval | — | No |
| 12 | presentation_composer | Presentation Composer | storyline_builder, si_retrieval | Yes |
| 13 | pptx_renderer | PowerPoint Renderer | presentation_composer | No |

### Dependency Graph

```
brief_scope
  └─ background_research*
       ├─ search_strategy*
       │    ├─ query_evaluation
       │    ├─ dataset_upload
       │    └─ research_planner* (also depends on background_research, dataset_upload)
       │         └─ research_executor
       │              └─ evidence_library
       │                   └─ insight_generator*
       │                        └─ storyline_builder*
       │                             └─ presentation_composer* (also depends on si_retrieval)
       │                                  └─ pptx_renderer
si_retrieval (independent)
```

`*` = requires human approval before downstream stages proceed

### Parallel Execution

Stages 4 (Query Evaluation) and 5 (Dataset Upload) run concurrently since both depend only on Search Strategy. Stage 11 (SI Retrieval) is fully independent and can run in parallel with any stage. The orchestrator uses `ThreadPoolExecutor(max_workers=4)` for parallel groups.

## Execution Modes

| Mode | Behavior |
|------|----------|
| `full` | Run all 13 stages in dependency order |
| `from_stage` | Run from a specified stage through the end |
| `single` | Run one stage only |
| `changed` | Run only stages where cache is stale |
| `resume` | Resume a paused/failed/awaiting_approval run |

## Cache System

Each stage's input is hashed (SHA-256) based on project ID, stage ID, and dependency states. On execution:
- **Cache hit**: stage returns immediately with cached result
- **Cache miss**: stage executes, result is cached on success
- Cache entries stored in `intel_pipeline_cache` table
- `invalidate_downstream_cache()` clears all downstream entries when a stage changes

## Failure Recovery

When a stage fails:
1. All downstream stages are marked "skipped"
2. Completed stages and their outputs are preserved
3. Pipeline status set to "failed"
4. User can retry the failed stage or resume from it

## Approval Gates

Six stages require human approval. When an approval-gated stage completes:
1. Pipeline pauses with status "awaiting_approval"
2. User approves through the existing stage UI
3. User calls Resume to continue the pipeline

## Database Tables

| Table | Purpose |
|-------|---------|
| `intel_pipeline_runs` | Pipeline run tracking (status, mode, progress, stages) |
| `intel_pipeline_stages` | Per-stage state within a run (status, timing, cache, result) |
| `intel_pipeline_cache` | Cached stage outputs keyed by project+stage+input_hash |
| `intel_pipeline_logs` | Execution log entries with level and stage context |
| `intel_pipeline_metrics` | Performance metrics (execution times, durations) |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/pipeline/start` | Start pipeline (mode, project_id) |
| POST | `/pipeline/{run_id}/pause` | Pause running pipeline |
| POST | `/pipeline/{run_id}/resume` | Resume paused pipeline |
| POST | `/pipeline/{run_id}/cancel` | Cancel pipeline |
| POST | `/pipeline/{run_id}/retry` | Retry failed stage |
| POST | `/pipeline/run-stage` | Run single stage |
| POST | `/pipeline/run-from` | Run from specified stage |
| GET | `/pipeline/status/{run_id}` | Pipeline run status with stages |
| GET | `/pipeline/project/{project_id}` | Full project pipeline status |
| GET | `/pipeline/timeline/{run_id}` | Execution timeline |
| GET | `/pipeline/logs/{run_id}` | Pipeline logs |
| GET | `/pipeline/metrics/{project_id}` | Performance metrics |
| GET | `/pipeline/cache/{project_id}` | Cache metrics |
| POST | `/pipeline/cache/{project_id}/clear` | Clear cache |
| GET | `/pipeline/graph` | Dependency graph |
| GET | `/pipeline/stages/{project_id}` | Project stage statuses |

## Frontend

The Pipeline Orchestrator page (`PipelineOrchestratorPage.tsx`) provides:
- Project selector
- Summary cards (stages, total runs, avg duration, cache entries, current stage)
- Action bar (Start Full, Run Changed, Resume, Pause, Cancel, Clear Cache, Refresh)
- Progress bar for running pipelines
- 5-tab layout: Stages / Logs / Timeline / Metrics / Cache
- Stage table with status badges, dependency info, run/retry actions
- Stage inspector panel (dependencies, downstream, approval requirement, run/clear actions)
- Execution timeline with duration bars and cache hit indicators
- Performance metrics with stage average bars and cache breakdown

## Tests

83 automated tests across 10 test classes:
- DependencyManagerTest (18): graph traversal, upstream/downstream, parallel groups, invalidation
- StageDefinitionTest (7): structure, ordering, circular dependency detection
- CacheManagerTest (7): hashing, hit/miss, clear, invalidation
- StageStatusCheckerTest (5): real DB state checks per stage
- PipelineStoreTest (10): CRUD for runs, stages, cache, logs, metrics
- DetermineStagesTest (5): mode-based stage selection
- PublicAPITest (14): error paths for all public methods
- PipelineStatusTest (8): status, timeline, logs, metrics, cache queries
- ExecutionEngineTest (5): single stage execution, convenience wrappers
- StageExecutorIntegrationTest (4): executor registration, execution

## Known Limitations

1. Pipeline runs synchronously in the request thread. Long-running pipelines block the HTTP response until completion or approval pause.
2. SI Retrieval checks the global SI library, not per-project indexed slides.
3. Cache invalidation is input-hash based only. Manual data changes outside the pipeline won't trigger cache refresh.
4. Parallel execution is limited to `max_workers=4` threads.
5. No WebSocket push for real-time progress — frontend polls via Refresh button.
