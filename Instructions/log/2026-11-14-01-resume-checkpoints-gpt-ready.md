# 2026-11-14-01 Every stage resumes after a restart; models that cannot read images; Azure GPT-5 cut-off retry; every chart category explained in the insight step

## Request
After my read of the Deliverables stage (strengths, and these weak spots: 96-121 min runs; a restart throws a run away; the
"every category has an insight" check only fixed by repair; model choice by trial and error; fallback cards), the user
asked for the following:
- "make the weak spot strong".
- "any stage unfinished jobs can be resume from where it stop ... irrespective of system restart". Asked to choose
  between replaying the saved AI answers and full checkpoints, the user answered "each stage should have check pointt
  ... not start from the beggining + Option 2" (full checkpoints).
- "fix llm we are using Chat gpt -4/5 once we get api". Answer "1 +2": get GPT ready AND build the per-model vision flag.
- Move the category-coverage check into the insight step: "Yes, include it".
(No log was written for the two previous answers, which explained the Deliverables stage and gave my opinion of it.
This note covers them; they changed no code.)

## What changed
- **Migration 0006** (`0006_resume_checkpoints.py`): `intel_jobs.params_json`, table `intel_checkpoints` (owner, step,
  project_id, payload_json; found by project deletion through its project_id column), `org_llm_providers.reads_images`.
- **Job resume** (`core/jobs.py`):
  - `resumable(job_type)` registers the job body `fn(job_id, project_id, **params)`.
  - `launch()` saves the inputs plus the caller's org and user, then submits the job.
  - `resume_interrupted()`, called at startup, starts every running or queued job again. It runs inside
    `usage.scope(org, user)` and `memory.replay(job.created_at)`; a job with no saved inputs is canceled.
  - Repository functions (`projects/repository`): `claim_interrupted_jobs(booted_at)` claims each row once,
    `save_checkpoint`, `get_checkpoints`, `clear_checkpoints`. `cancel_stale_running_jobs` was deleted. Job reads never
    return the inputs.
- **Workers moved out of the endpoints and registered** (closures became module functions):
  - Brief & Scope: `spec/router._spec_job`; generate and regenerate were near-copies and are now merged.
  - Background Research: `research/router._research_job`, with checkpoint "web". On resume it skips the web search and
    goes straight to enrichment.
  - Search Strategy: `strategy/router._strategy_job`.
  - Sample evaluation and Data set parse: `_sample_evaluation_job` and `_process_dataset_bg`.
  - Research Plan: `plan/router._plan_job`. QC: `qc/router._qc_job`.
  - Data set tagging: `dataset/tagging_job._tagging_job`. It already re-tags only what is missing.
- **Replay** (`memory.replay(since)`): inside `fresh()`, an AI answer saved since the job started is recalled, so the
  steps finished before the restart cost no call.
- **Deck runs** (`deliverable/engine.py`):
  - At startup `resume_interrupted_runs()` continues each running run on the same run id and log.
  - `_Run(resume=True)` keeps the log, rewrites the content sections and reads the run's checkpoints.
  - Checkpoints: `insights:<RQ>` (cards, summaries and a registry snapshot, so citation numbers continue),
    `insights:_brand`, `template`, and `render` (classic deck, Word brief and fact check, reused when the files exist).
  - Checkpoints are cleared when the run ends. Plans, classifications, photos and screenshots were already stored per
    item.
  - Repository: `fail_interrupted_deliverable_runs` became `claim_interrupted_deliverable_runs`, plus
    `clear_run_content_sections`.
- **Latest-24h refresh**: `latest24h.resume_interrupted()` runs it again on the same row, replaying answers it already
  got (`claim_interrupted_latest24h_refreshes`).
- **Fix found live** (commit af1a803): at startup there is no org scope, so with the platform model off,
  `get_llm_client()` returned None. The resumed deck run then went on with rule-based cards (test run 4, discarded). The
  deck and refresh resumes now build the client inside the project's scope, and a run with no client fails rather than
  degrading.
- **Models and images**:
  - `llm_provider._has_images` and `_image_readers` send an image request only to models whose `reads_images` is not 0.
    If none can, the call raises `OrgProviderError`.
  - `providers.service.call` marks a model 0 the first time it refuses an image (the "capability" class).
  - LLM Providers form: a "Reads images" choice (Not known / Yes / No) and a badge in the list.
  - API: `reads_images` added to the provider schemas.
- **GPT readiness** (`azure_openai_client.chat`): a GPT-5 reply cut off by its thinking (finish=length, not streamed) is
  asked once more with `reasoning_effort=low`. GPT-4 deployments still raise `ReplyCutOff`. The GPT-4 and GPT-5
  parameter handling already existed.
- **Every chart category explained in the insight step** (`engine_insights._every_segment`):
  - A category still missing a card after the retry is drafted from its own articles only. If no article explains it,
    its number is read from the chart (`count_reading.readings`, count_only), as the repair agent does.
  - When every card is count-only, a cited summary leads them.
  - `deckstudio/planner` now allows one extra card (SEGMENT_CARDS + 1) for that leading summary.

## Verified
- New local tests:
  - `tests/core/test_resume.py` (7): claim once, resume with inputs, scope and replay, launch, checkpoints, the replay
    window, the deck `_Run` resume, and the client built in the project scope (regression).
  - `tests/providers/test_reads_images.py` (5).
  - `test_migrations` 0006 up and down; table count 120.
- Updated tests: 2 tagging tests (they patch `jobs.runner`), the Azure stream test (GPT-4 path), the client-usage test
  (both paid calls are recorded), the failover image test (stubs the mark), and the engine fake store
  (`clear_checkpoints`).
- Full `pytest -q tests` (minus e2e_3org): 736 passed. ruff and vulture clean. Frontend tsc clean, lint 0 errors,
  `npm test` 15 passed, build done.
- **Live, Test Organization project 38, NVIDIA models only (Azure blanked):**
  - Migration 0005 to 0006 applied at startup.
  - Deck run 5: I killed the server mid-insights, after RQ2 was checkpointed (12 min in) and while RQ1 was drafting.
  - After the restart, startup logged "1 deck runs ... resumed". The run log reads "Resumed after a server restart;
    already finished: insights:RQ2", then "RQ2 ... 3 insights kept from before the restart".
  - Gate to compute took 3 seconds. RQ1's 18 AI calls made before the crash were replayed from cache (llm_usage
    cache_hit=1); only new work went live.
  - Run 5 completed. Validation: 17 of 17 checks pass before repair ("nothing it can repair"; repair took 0 min against
    22-28 min in runs 2 and 3). 0 fallback cards, 33 slides, 16 photos.
  - Total 68 min including the crash, against 96 and 121 min for runs 3 and 2.
  - Timings (min): insights 29.2 after the resume (plus 12 before the crash), render 6.2, assets 17.9, repair 0.0.
  - Nemotron 3 Ultra refused one image and was marked `reads_images=0` automatically: 1 refusal, against 12 in run 3.
  - The `deck:5` checkpoints were cleared after the deck was saved to S3.

## Not verified / open
- Resume of the non-deck jobs was not run live: no project was created for it, and re-running strategy or research on
  project 38 would overwrite its data. Only the unit tests cover it.
- The latest-24h refresh resume was not run live.
- The Azure GPT-5 low-reasoning retry is unit-tested only (no GPT spend allowed). The LLM Providers "Reads images"
  control was not clicked through in a browser.
- `claim_interrupted_deliverable_runs` has no per-process marker (a `shortcut:` comment says so); we run one uvicorn
  process. Jobs are claimed with the boot-time filter.
- The batching A/B stays paused until GPT spend is approved.
- Project 38 now has runs 4 (discarded test, failed) and 5 (completed). It is still kept for the user's review; cleanup
  is waiting on the user's word.
