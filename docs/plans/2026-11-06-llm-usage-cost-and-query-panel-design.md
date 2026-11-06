# LLM usage and cost tracking, Usage & cost dashboard, Data set query panel, and LLM call cuts — design

Date: 2026-11-06 · Status: approved in brainstorming

## Goals

1. Track the tokens and cost of every LLM call by org, project, stage, model and day.
2. Add a Usage & cost dashboard with:
   - a date-range calendar, a trend line, bar charts and tables
   - provider logos everywhere
   - an entry from the sidebar, and from an icon on each project card that opens the dashboard filtered to that project
3. On the Data set page, show each approved research question (RQ) and its Boolean query, with a drill-down to review, edit, delete, update and re-tag it.
4. Cut LLM calls without losing quality. Each cut is proven with before/after numbers from goal 1.

## 1. Capture (backend)

**Hook points.** Every paid call passes through 3 clients. Each one calls `usage.record(...)` after the response:
- `core/azure_openai_client.py`: `chat` (stream and non-stream) and `chat_tools`
- `core/nvidia_embed_client.py`: `_embed_texts`
- `core/nvidia_parse_client.py`: `_parse_image`

The ~40 call sites stay unchanged.

**What each record holds.**
- **Recorded before raising.** A reply cut off at `max_completion_tokens` is still billed, so it is counted.
- **Streaming.** The request sends `stream_options: {"include_usage": true}`, and the usage is read from the last chunk.
- **The real model.** The record stores the response's `model` (e.g. `gpt-5-2025-08-07`), not the deployment name.
- **Cache hits.** A memory-cache hit in `core/llm_provider.py` is logged as a 0-token row with `cache_hit=true`. That row feeds the "saved by cache" figure.

**Table `llm_usage`** (migration 39; 36 stays reserved). One row per call. No prompt text is stored.

| Field | Meaning |
|---|---|
| `ts` | Call time, UTC |
| `org_id`, `project_id`, `stage`, `user_id` | Who made the call, and where |
| `provider` | `azure_openai`, `nvidia`, `typesafe` or `tavily` |
| `model` | Real model name from the response |
| `deployment_type` | Azure deployment type |
| `kind` | `chat`, `tools`, `embed`, `parse` or `request` |
| `input_tokens`, `cached_input_tokens`, `output_tokens`, `total_tokens` | Token counts |
| `requests`, `credits` | Per-request services |
| `latency_ms` | Time the call took |
| `cache_hit`, `error` | Flags |
| `cost_usd` | Computed when the row is written |

**Scope: who and where.**
- One ContextVar holds `(org, project, stage, user)`.
- A FastAPI middleware sets it from the request: the project from the URL, the stage from the route prefix.
- Job entry points set it explicitly: tagging, deck engine, Deck Studio, autorun / autopilot / copilot, research jobs and QC.
- `core/jobs.submit` and the ~13 inner thread pools wrap work in `contextvars.copy_context().run`:
  - `engine`, `latest24h`, `extract`
  - `creative`, `pipeline`
  - `multi_source`, `news_search`, `extra_sources`, `research/router`
  - `tagging_job`, `qc/service`
- This also fixes Regenerate (`memory.fresh()`) being lost inside those pools.

**Stages:** Brief & Scope · Background research · Search strategy · Matching label · Data set tagging · Deck engine · Deck Studio · Agent · QC.

**Prices (table `llm_prices`).** Each row holds the model, deployment type, input / cached-input / output price per 1M tokens, and an effective date. Past costs never change when prices change.

- **Azure.** A daily sync reads Microsoft's public Retail Prices API (`prices.azure.com`, meters under `Foundry Models`).
  - The default deployment type is Global Standard, editable in Settings.
  - GPT-5 Global, effective 2025-08-01: input $1.25, cached input $0.125, output $10.00 per 1M tokens.
- **NVIDIA** (`integrate.api.nvidia.com`, the API catalog).
  - The catalog uses credits and has no published per-token price. Tokens, requests and credits are logged at $0.
  - A Super Admin field sets a price per 1M tokens for when the account moves to a paid endpoint.
  - **Licence risk:** the catalog terms allow prototyping only. Production use needs an NVIDIA AI Enterprise licence.

**Safety.** Recording never breaks an LLM call. If the insert fails, a warning is logged and the answer is still returned.

## 2. Usage & cost dashboard (frontend)

**Entry points**
- The `IconRailSidebar` icon **Usage & cost** opens `/usage`.
- The usage icon on each project card shows the cost so far on hover and opens `/usage?project=<id>`.

**Visibility**
- Users see their own projects.
- Admins see their whole org.
- The Super Admin sees all orgs, through an Org filter.

**Filters**
- A From / To calendar with presets: Today, 7 days, 30 days, This month, Custom.
- Org, Project, Stage and Model, with logos in the options.
- All filters are kept in the URL.

**KPI tiles:** total cost · tokens (input / output) · calls · saved by cache ($ and %) · NVIDIA credits used.

**Charts** (amCharts 5). Every legend shows the provider logo with the full model name.
- Daily trend line of cost or tokens: one line per model, plus a dashed total.
- Stacked bars (input / cached / output) by model, stage or project.
- Stage breakdown when one project is selected.

**Tables**
- **Summary:** logo with the full model name, provider, deployment type, calls, input, cached input, output, total and cost. It has a totals row and sorts by any column.
- **Call log:** date and time, project, stage, logo with the model, kind, input, output, total, cost, latency and cache hit. It shows 50 rows per page. Clicking a summary row filters the log to that row.
- Both tables export to CSV.

**Logos.** Iconify's official Microsoft Azure, OpenAI and NVIDIA logos. The SVGs are also saved in the S3 asset library for reuse.

**API.** Every endpoint is scoped server-side to what the caller may see.
- `GET /api/usage/summary`
- `GET /api/usage/calls`
- `GET /api/usage/prices` for all users; `PUT /api/usage/prices` for the Super Admin only

**Empty and error states.** "No LLM calls in this range"; on error, the message and a Retry button.

## 3. Data set page: research questions and Boolean queries

**Panel.** A collapsible **Research questions** panel above the table. Each approved RQ shows:
- its text and a preview of its query
- counts: matched, tagged, approved, needs tagging
- a status chip

**Drawer.**
- The full RQ text.
- A Boolean query editor with highlighting and a live `validate_boolean_syntax` check. An invalid query cannot be saved.
- **Preview** (free keyword matching): match counts for the current and the edited query, the +N new and −M dropped articles, and their titles.
- Buttons: Save query · Re-tag this question · Delete question · Cancel.

**Save (option A).**
1. Save through the same RQ API the Matching label tab uses.
2. Re-match the new query against every uploaded article at once. This is free.
3. Newly matched articles become **needs tagging**. They are kept out of the deck until they are tagged and approved.
4. Articles that no longer match:
   - pending articles become *No match*
   - approved or rejected articles keep their decision and get a "query changed: no longer matches" flag. The analyst decides.

**Re-tag.**
- First an estimate: articles · batches · tokens · cost. It comes from the tagger's own token budgets and the live price.
- Only the articles that need tagging are tagged. Progress shows in the tagging strip.
- The cost is logged under Data set tagging.

**Delete.** A confirmation that states how many approved articles will leave the deck. Uploaded articles and their article-level tags stay.

**Guards.**
- Editing is blocked, with the reason shown, while tagging or a deck run is in progress.
- Only the project owner or an admin can edit.

## 4. LLM call cuts, each proven before it ships

Tracking from section 1 must be live first, to give a baseline. Then each cut ships alone.

**Proof for each cut:** the same project, before and after.
- **Cost:** the dashboard delta for the affected stage.
- **Quality:**
  - decks keep the same RQ sections and headline numbers
  - insight cards still pass the number and citation checks
  - theme titles stay professional
  - tags agree on at least 95% of articles
- The user reviews the result. A cut that lowers quality is reverted.

| # | Cut | Proof |
|---|---|---|
| 1 | Prompt-prefix caching: fixed text first, variable text last | Identical outputs; the cached-input share rises |
| 2 | The deck engine reads entities from approved Data set tags instead of calling `extract.py` again; GPT is used only for fields the tagger lacks | Same entity charts on 2 projects |
| 3 | `HUNTER_BATCH_INSIGHTS=1`: 3 calls per RQ instead of 3–8 per section | Card-by-card A/B on 2 decks |
| 4 | Reuse photos from the S3 asset library before any vision call | Same photo-fit pass rate |
| 5 | A cheaper model for yes/no calls (`entity_relevance`, `count_reading`, theme grouping) | At least 98% agreement per call type, or that call type stays on GPT-5 |
| 6 | Cache unchanged deck sections on Regenerate | Byte-identical sections |

Kept as they are: one GPT judgement per RQ in tagging (a spec requirement), and the 7-day memory cache.

## Testing

**Unit tests** (local, gitignored):
- Recording:
  - Azure non-stream, stream, cut-off and tool calls
  - embeddings
  - cache hits
  - a failed insert never breaks the call
- The scope survives thread pools.
- Prices are picked by effective date.
- Role scoping.
- Query re-match: newly matched articles become needs tagging, and decided rows keep their decision.

**Live Playwright** (inside the 500-article cap):
- Dashboard totals agree with Azure usage for the same window.
- The project-card icon and the sidebar icon work.
- Logos appear in the legends and the tables.
- Edit a query, preview, save and re-tag. The estimate comes close to the logged actual.

## Build order

This starts after the current plan finishes: Task 18 local end-to-end, then Tasks 3–6.

1. Capture (section 1)
2. Dashboard, icons and price sync (section 2)
3. Data set query panel (section 3)
4. Cuts 1–6, one at a time (section 4)
