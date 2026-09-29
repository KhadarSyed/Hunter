# Multi-Source Research Pipeline — Design Spec

Status: approved (brainstorming), pending implementation plan
Date: 2026-09-29
Owner: Hunter Intelligence Platform — Background Research stage

## 1. Problem

Background Research (`web/src/pages/BackgroundResearch.tsx`, backend `domains/research/`) fetches
web results using plain-string queries built from stale spec fields, then composes a Brief with a
single LLM call that silently drops any data beyond fixed truncation caps. Specifically:

- `web_research.py::build_search_queries()` produces plain concatenated strings, not Boolean
  queries, and several of its inputs read spec fields that `agents/brief_scope.py` no longer
  writes to (`_extract_competitors()` reads `spec.competitors`/`spec.source_spec.competitors`;
  real data is at `spec.included_scope.competitors`. `_extract_products()` reads
  `spec.commissioning_brand.products`, which never exists. `_extract_category()` falls back to a
  crude keyword heuristic instead of using `spec.industry.name`). Net effect: competitor- and
  product-specific searches never fire; category searches are generic ("general").
- Date-range filtering is soft/advisory: unparseable dates are kept, out-of-range items are
  retained as "background context" rather than dropped, and only Google News RSS receives any
  real upstream date bound.
- `research/service.py::compose_brief()`/`_compose_with_llm()` makes one LLM call with hard
  truncation (`[:20]` brand items, `[:15]` industry items, `[:8]` per competitor, `[:30]` sources)
  — data beyond these caps is silently dropped, with no batching/map-reduce.
- No item-level persistence: research results live only as one JSON blob per run
  (`intel_background_research.research_json`), not as individually queryable rows.
- A previously-considered Phyllo integration for social-media search does not fit this use case
  (see §7) and is out of scope for this phase.

## 2. Goals

1. Every topic query includes both the brand and its competitors, OR'd together, so no query is
   blind to the competitive set.
2. Real Boolean query syntax (quotes, AND/OR, minus-exclusion) sent to SerpAPI and Google RSS;
   an equivalent natural-language rendering sent to Tavily.
3. Concurrent fan-out to 3 sources (Tavily, SerpAPI, Google News RSS) per topic query, replacing
   today's sequential one-query-at-a-time-with-sleep loop.
4. Stringent date-range filtering: real API-level date bounds where supported, hard client-side
   cutoff otherwise (no more "keep it anyway" on unparseable/out-of-range items). Default lookback
   is 7 days for this POC phase (see §8), with 30/90/180/365-day options retained.
5. All normalized results persisted per-item in a new DB table, linked to `project_id`, dedup'd by
   `(project_id, url)`.
6. Brief composition becomes map-reduce: batch-summarize all persisted items (no truncation caps),
   then combine batch summaries into the existing Brief section schema — zero frontend changes.
7. Every LLM call in this pipeline (and, as a small drive-by fix, `brief_scope.py`'s existing
   calls) receives the real current date/time computed in Python, never left for the model to
   infer.
8. The fetch engine is stage-agnostic: usable by Background Research now, and by Research
   Execution (stage 6) later once Search Strategy's approved query is available.

## 3. Non-goals

- Phyllo / social-listening integration (dropped this phase — see §7).
- Changing the Search Strategy stage's Meltwater-flavored Boolean query builder
  (`agents/meltwater_query_builder.py`) — it stays as-is; this project reuses its term-extraction
  *pattern*, not its code, for a different (non-Meltwater) rendering target.
- Wiring the new fetch engine into Research Execution (stage 6) in this phase — the engine is
  designed to support it later, but that caller is not built now.
- Any change to the Search Strategy or Query Evaluation pages/endpoints.

## 4. Architecture

New module: `agent/app/domains/research/multi_source.py`, exposing three functions:

```python
def build_boolean_queries(spec: dict) -> list[TopicQuery]: ...
def fetch_multi_source(topic_queries: list[TopicQuery], date_range: tuple[date, date],
                        geography: str, project_id: int, research_id: int | None) -> FetchResult: ...
def summarize_map_reduce(project_id: int, spec: dict, llm_client) -> BriefSections: ...
```

**Existing code changes, not a parallel system:**

- `web_research.py::LiveWebResearchAdapter.run_full_research()` calls `build_boolean_queries()` +
  `fetch_multi_source()` internally instead of `build_search_queries()` + its sequential loop.
  Same job worker (`research/router.py::start_background_research`), same `POST /research/start`
  endpoint, same WS progress events (`intel_job_update`) — only the internals change.
- `research/service.py::compose_brief()`/`_compose_with_llm()` calls `summarize_map_reduce()`
  instead of making one fixed-truncation LLM call. Output shape is unchanged
  (`company_introduction, executive_summary, brand_developments, brand_narrative,
  competitor_developments, industry_context, key_issues, source_register, methodology`), so
  `BackgroundResearch.tsx` needs no changes.
- One new endpoint, `POST /api/intel/research/fetch-preview`, exposes `fetch_multi_source()`
  directly — for standalone testing now, and as the entry point Research Execution will call
  later. Same async-job pattern as every other long-running endpoint this session
  (`store.create_job` → immediate `job_id` response → `core.jobs.submit` worker → `intel_job_update`
  WS progress → `store.update_job(status="completed", result=...)`).

## 5. Boolean query builder

**Term groups**, extracted from the approved Research Specification (mirroring
`domains/strategy/router.py::_build_deterministic_strategy()`'s grouping, not its Meltwater
output renderer):

- `brand_terms` — commissioning brand name (`spec.commissioning_brand.name`)
- `competitor_terms` — `validated_entities` where `type == "competitor"`
- `product_terms` — `validated_entities` where `type in ("product", "product_group")`
- `category_terms` — `spec.industry.name` (fixes the dead-field bug in §1), falling back to
  `research_subject.description` only if `industry.name` is empty
- `event_terms` — `validated_entities` where `type == "event"`
- `exclude_terms` — `excluded_scope` descriptions

**Core group**: `brand_or_competitors = OR(brand_terms + competitor_terms)`, threaded through
every topic query (per explicit correction during design review — no topic is brand-only or
competitor-only).

**Topics produced**, each with a `.boolean_query` (SerpAPI/Google RSS) and `.natural_query`
(Tavily) rendering:

| Topic | Boolean rendering | Natural rendering |
|---|---|---|
| `brand_activity` | `(brand_or_competitors) AND (news OR announcement OR campaign)` | `<brand>, <competitors> news and announcements` |
| `competitive_landscape` | `(brand_or_competitors) AND (<category terms>)` | `<brand>, <competitors> <category> market` |
| `product_mentions` | `(brand_or_competitors) AND (<product_terms OR'd>)` | `<brand>, <competitors> — <products>` |
| `category_trends` | `(brand_or_competitors) AND "<category>" AND (trend OR market)` | `<category> market trends: <brand>, <competitors>` |
| `events` | `(brand_or_competitors) AND "<event>"` (one per event) | `<brand>, <competitors> — <event>` |
| `research_question_N` (≤3) | `(brand_or_competitors) AND` quoted key phrase from RQ | same, plain language |

Exclusions apply as `-"term"` appended to `.boolean_query` only. Tavily has no exclusion operator,
so excluded terms are filtered out of Tavily results post-fetch via substring match on
title/content.

## 6. Normalized schema + persistence

```python
class NormalizedItem(TypedDict):
    publication: str
    published_date: str   # ISO 8601, always present — falls back to fetch date if source gives none
    title: str
    content: str
    url: str
    source_api: str        # "tavily" | "serpapi" | "google_rss"
    topic: str
    platform: str | None   # domain-derived: "twitter", "reddit", etc., or None
```

New table (migration, following the existing `MIGRATIONS` list pattern in `core/db.py`):

```sql
CREATE TABLE intel_research_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    research_id INTEGER,              -- FK to intel_background_research; nullable for fetch-preview calls
    topic TEXT NOT NULL,
    source_api TEXT NOT NULL,
    platform TEXT,
    publication TEXT,
    published_date REAL NOT NULL,
    title TEXT,
    content TEXT,
    url TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(project_id, url),
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (research_id) REFERENCES intel_background_research(id)
);
CREATE INDEX idx_research_items_project ON intel_research_items(project_id);
CREATE INDEX idx_research_items_project_date ON intel_research_items(project_id, published_date);
```

Upsert on `(project_id, url)` conflict (same pattern as `brand_logos`/`pexels_images`): reruns
update existing rows rather than duplicating. Items are written as they're collected during fetch,
not batched at the end, so a worker crash mid-run still leaves partial results queryable.

## 7. Fetch engine: concurrency, date filtering, degradation, Phyllo decision

**Concurrency**: per `TopicQuery`, fan out to all 3 sources via `ThreadPoolExecutor(max_workers=3)`
with `as_completed(..., timeout=SOURCE_TIMEOUT_S)`. ~6 topics × 3 sources = ~18 calls total, run
concurrently per topic, replacing today's up-to-~20-sequential-queries-with-1.5s-sleeps pattern.

**Adapters** follow the existing house style (`brandfetch.py`/`pexels.py`/`news_search.py`): never
raise, catch their own exceptions, return `[]` on failure; a `LookupUnavailable`-style signal
distinguishes "no results" from "source errored" so degradation can be flagged per-source
(`intel_background_research.research_json._source_status = {"tavily": "ok", "serpapi": "degraded", ...}`),
surfaced in the UI the same way `search_degraded` already is today.

**Date filtering — hard, not advisory**:
- `_extract_date_range()` gains two new branches: `"7 day"` / `"past week"` (POC default, see §8)
  and a fallback that no longer silently defaults to 365 days for unmatched strings.
- Real API-level date bounds passed where supported: Tavily's `days` param, SerpAPI's Google-News
  `tbs` custom-date-range param, Google RSS's `when:{days}d`.
- Post-fetch, items outside the window — or with unparseable dates — are **dropped**, not kept.
  This flips today's explicit "keeping item despite date_range filter" behavior
  (`news_search.py::_within_range()`).

**Phyllo — dropped from this phase.** Investigated during design: Phyllo's primary product is
"Connect," an OAuth-style flow requiring a specific individual to register as a Phyllo user and
interactively link their own social account (`POST /v1/users` → `POST /v1/sdk-tokens` scoped to
`IDENTITY`/`ENGAGEMENT`/`INCOME`/`ACTIVITY` → client-side `PhylloConnect` widget). This has no
account for "the general public talking about a brand" to connect, so it cannot power brand/
competitor mention search. Phyllo separately advertises a "Social Listening API" with Boolean/
keyword mention tracking, but its exact request/response schema could not be confirmed (JS-
rendered docs, not fetchable), and `SOCIAL_LISTENING` is not among the product scopes in the
Connect example provided. Decision: ship with 3 sources now; revisit Phyllo (or another social-
listening source) as a follow-up phase once Social Listening's availability/schema is confirmed
directly from the account holder.

## 8. Map-reduce summarization

Replaces `research/service.py::_compose_with_llm()`.

- **Batching**: query `intel_research_items` for the project (all items, no truncation), split
  into batches of ~15-20 items, grouped by `topic` so each batch stays thematically coherent.
- **Map step**: one LLM call per batch, progress emitted per batch over `intel_job_update` WS
  (same pattern as the rest of this session's streaming work). Each batch summary:
  `{topic, key_points: [...], notable_sources: [...]}`. Failed batches are skipped and logged, not
  fatal.
- **Reduce step**: one final LLM call takes all batch summaries (now small regardless of original
  item count) and produces the existing Brief section shape
  (`company_introduction, executive_summary, brand_developments, brand_narrative,
  competitor_developments, industry_context, key_issues, source_register, methodology`).
  `source_register` stays deterministic, built from `intel_research_items` rows directly.
- **Fallback**: `_compose_rule_based()` remains the final safety net if the reduce step itself
  fails entirely — unchanged from today.
- **Current date/time injection**: every LLM call in this pipeline (map, reduce, and as a small
  drive-by fix, `agents/brief_scope.py`'s existing calls) has the real current date/time computed
  in Python (`datetime.now()`) injected into the prompt, so the model is never asked to infer
  "today's date" itself.

## 9. Frontend change: Time Period dropdown

`web/src/pages/NewProject.tsx` — add a "Past 7 days" option to the Time Period `<select>`
(currently `Past 30 days | Past 3 months | Past 6 months | Past 12 months`), and change the
default selected value from `"Past 30 days"` to `"Past 7 days"` for this POC phase, per explicit
request. The other four options remain available and unaffected.

## 10. API surface

`POST /api/intel/research/fetch-preview`
- Body: `{project_id: int, topics?: string[]}` (omit `topics` to run all topics for the project's
  spec)
- Returns immediately: `{job_id: str, project_id: int}`
- Progress: `intel_job_update` WS messages, same shape as every other async job this session
- Result: `job.result = {"items_fetched": int, "items_persisted": int}`; actual data is queried
  from `intel_research_items` by `project_id`

No changes to `POST /research/start`'s external contract — its internals now call the new engine,
but request/response shape is unchanged.

## 11. Testing

- Unit tests: `build_boolean_queries()` term-group extraction and both renderings; the new
  date-range branches in `_extract_date_range()`; upsert-dedup behavior on `intel_research_items`
  (rerun does not duplicate rows).
- Acceptance test (live, post-implementation): create a fresh **Tesla** project (client ask,
  "Past 7 days" time period), run Brief & Scope → Background Research, and confirm:
  - every topic's persisted `intel_research_items` rows include both Tesla and competitor mentions
  - all `published_date` values fall within the 7-day window
  - the final Brief's section content reflects sources beyond the old 20/15/8/30 truncation caps
  - `research/fetch-preview` returns a job that completes and persists items independent of a full
    research run

## 12. Open items for the implementation plan (not blocking spec approval)

- Exact batch size for map-reduce (target ~15-20 items/batch; final number set during
  implementation based on observed prompt-token usage).
- Exact `SOURCE_TIMEOUT_S` value for the per-source concurrent fetch.
- Whether `intel_research_items.content` needs a length cap at write time (existing per-item
  300-char truncation happens at prompt-build time today; decide whether to preserve full content
  in the DB regardless, given batching removes the pressure to truncate early).
