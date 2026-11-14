# 2026-11-14-02 Test Org model prices; live crash-and-resume test of every stage (project 39); three bugs it found

## Request
- "Input / 1M tokens $2.00 $1.25; Cached Input / 1M tokens $0.50 $0.13; Output / 1M tokens $8.00 $10.00 — update
  these prices for testing llm". Asked which column belongs to which model, the user answered "All three get column A".
- "create another project on testing org to test live what remain". Asked about scope: "Every stage + crash each".

## Prices (data only, no code)
- `PUT /api/intel/usage/prices` as the Test Organization admin, provider `openai_compatible`, $2.00 / $0.50 / $8.00
  per 1M tokens, for `nvidia/nemotron-3-ultra-550b-a55b`, `minimaxai/minimax-m3.1-flash` and
  `stepfun-ai/step-5-preview`.
- Each first price was back-dated to the model's first use (2026-11-12) and re-costed its earlier calls: 397, 191 and
  22 calls.
- Usage summary (30 days): $6.35 total, `unpriced_models` 0.

## Live test: project 39 "SYNTHETIC RESUME TEST - delete after checks" (Test Organization, NVIDIA only, Azure blanked)
Each stage ran through the real API as the org admin. The server was killed at a chosen point (scratch `kill_at.py`
waits for a SQL condition, then kills the port-8002 process) and restarted.

| Stage | Killed when | After the restart |
|---|---|---|
| Brief & Scope (generate) | first AI call done | resumed, completed (spec 38, source `llm`); found bug 1 |
| Brief & Scope (Reanalyze) | mid-run, after the fix | resumed; every call tagged project 39 / brief_scope; 1 answer replayed from cache |
| Background Research, case A | mid web search (21%) | resumed, searched again (7.5 min), enriched |
| Background Research, case B | right after the `web` checkpoint (state recreated: the real gap is milliseconds) | "Resumed: web results already saved", no search, enriched, checkpoint cleared |
| Search Strategy | mid AI call (45%) | resumed, the call was redone (an answer in flight is never saved), the AI's strategy was saved |
| Data set tagging | 8 of 10 articles tagged | resumed; no article-tag calls repeated; question tags, themes and relations ran |
| Deck run 6 (4 questions) | mid brand-chapter summaries | "already finished: insights:RQ1-RQ4"; 15 brand-summary answers replayed, then live; completed with 40 slides, 13 photos, 24/29 checks |
| Latest-24h refresh 3 | 15 s in | "1 refreshes resumed"; completed, 56 fetched / 13 kept, summary source `llm` |

Run 6's 5 failed checks come from the synthetic data: RQ3 and RQ4 got 0 articles, and three brief asks (narrative
analysis, spokesperson tracking, gap analysis) have nothing to analyze. "Every chart category has its own insight"
passed.

## Bugs found and fixed
1. **A resumed job lost its stage and project** (commit b0562e0). `core/jobs.launch` saved only org and user, so a
   resumed Brief & Scope job ran as stage "other" with no project. Its 5 calls were unattributed, and the org's
   guardrails (added per stage) were left out of the prompt.
   - Fix: the saved scope now includes `stage` and `project_id` (`_SCOPE_FIELDS`).
   - Test: `test_launch_saves_inputs_and_the_whole_request_scope`.
2. **A query edit left newly matched articles Irrelevant** (commit 466cd15). `dataset/repository.apply_rematch` added
   the (article, question) rows but never set `intel_articles.rq_matched`. Since log 2026-11-13-17, tagging takes
   only matched articles, so a Matching label edit's new articles were never tagged, and dropped ones stayed in the
   pool.
   - Fix: the touched articles' flag is recomputed from their question rows and analyst decisions, in the same
     transaction.
   - Test: `test_query_edit_keeps_each_articles_matched_flag_in_step`. It fails on the old code.
3. **A model's `"summary": null` stopped a question's tagging step** (commit 1591c75). In `save_rq`,
   `result.get("summary", "")` returns None when the key is present with a null value, and the NOT NULL column
   refused the row. RQ2 kept 3 untagged rows.
   - Fix: `or ""` for summary and reason.
   - Test: `test_save_rq_takes_a_null_summary_and_reason`.

## Verified
- Full `pytest -q tests` (minus e2e_3org): 738 passed. ruff and vulture clean.
- The backend runs the latest code (backend20.log; Azure blanked).
- Other events during the run: one genuine Nemotron outage at 02:58. Failover went to MiniMax, and the
  switched/recovered emails went to the org admin. Nemotron was very slow tonight (3-15 min per call), which made
  deck run 6 take about 5 h.

## Not verified / open
- **Deck resume after the render checkpoint** (photo stage onward): my watcher waited for the photo stage's timing, but
  a stage's timing is written only when it ends, so the kill never fired. Another 4-question deck run on this slow
  model would take hours, so this was not repeated. Insights, brand and template resume are verified live (runs 5
  and 6). Photos and screenshots were already cached per slide.
- The "Reads images" control in LLM Providers was not clicked in a browser. The Azure GPT-5 low-reasoning retry is
  unit-tested only (no GPT spend).
- Auto-run after a spec approval started 3 extra research jobs on project 39 (existing behavior); all completed.
- The batching A/B stays paused until GPT spend is approved.
- Projects 38 and 39 stay for the user's review. `scratchpad/checks/cleanup.py` now deletes both (`extra_project_ids`
  in `created.json`) when the user says so.
