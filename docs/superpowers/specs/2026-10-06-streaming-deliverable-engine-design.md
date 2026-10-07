# Streaming Deliverable Engine — Design

**Date:** 2026-10-06 (revised 2026-10-07)
**Status:** REVISED — combined scope chosen 2026-10-07 ("generic visual deck" + "full streaming engine").
Awaiting approval of this revision before the implementation plan is written.
**Goal:** Hunter Agent itself turns an approved scope + RQs + uploaded Meltwater files into a client-grade,
cited, template-styled PPTX with charts, tables, images, logos, icons and labels — for **any** project —
and streams every section live on the Deliverables page. Project 261 (Baby Skincare) is the acceptance test.

## 1. Why

What already works (2026-10-07): uploads parse every sheet and encoding; Research Execution routes every
approved file to its RQ; coverage volume and unique stories are both measured; insights quote measured
figures; storyline/composer text is grounded. What is missing:

| Gap | Today |
|---|---|
| Pipeline deck is text only | `domains/rendering/pptx.py` builds 7 text slides from a blank `Presentation()` |
| The visual engine is hard-wired | `domains/deliverable/` (reference deck: native charts, tables, gauge, logos, citations) only knows Baby Skincare's deal / parenting / expert / celebrity themes and runs from a hand-written JSON + CLI |
| Analysis is keyword heuristics | `methods/executors.py`; theme shares like "baby eczema sale 89%" are keyword artefacts |
| No charts in the UI | no chart library in `web/` |
| Evidence has no citations | `intel_evidence` has no URL / document id |
| Validation does not fact-check | publishing scored a deck with invented text "100% ready" |

## 2. User flow

Brief → Scope → Background Research → Search Strategy → Data Sources (upload, enrich, review)
→ **Generate Deliverable** → the Deliverables page streams each stage and section → Download PPTX / DOCX.
Research Plan / Execution / Analysis stay reachable from the stage timeline for inspection but are no
longer required clicks — the engine runs them.

## 3. Engine (backend, `domains/deliverable/`, generalised)

Each stage persists its output and broadcasts on `/ws`: `deliverable_stage` (stage, status, timing),
`deliverable_section` (section id, kind, payload), `deliverable_completed`, `deliverable_failed`.
A failed stage stops the run visibly; nothing is invented to fill a gap.

1. **Gate.** Scope approved, strategy approved, ≥1 approved processed dataset.
2. **Ingest.** Reuse `execution._collect_dataset_records`: every approved file and sheet, enriched rows
   with the analyst's exclusions, `research_question_id` on every row, plus `url`, `document_id`,
   `source_file`, `row_index`. Coverage volume counts syndicated copies; unique stories are deduplicated
   with a `_copies` count.
3. **RQ routing.** Rows belong to the RQ their file was uploaded for; additionally each RQ's Meltwater
   Boolean query is evaluated locally (AND / OR / NOT, quoted phrases, parentheses, `*` wildcard,
   `NEAR/n` as co-occurrence within n words) over title + opening text + hit sentence + full text, so an
   article can answer several RQs. Base N = unique articles across all RQs; every share states its base.
4. **Analysis plan (LLM chooses, engine computes).** Per RQ the LLM receives the RQ text, the matched
   rows' column profile and a fixed **module catalog**, and returns a JSON plan (modules + chart kinds +
   titles). It never returns numbers. Catalog: share of coverage (KPI) · volume trend with top-5 peaks ·
   sentiment split · outlet / source-type ranking · reach · theme clustering · entity extraction
   (experts with type and brand affiliation, celebrities, brands, products, retailers) · brand share of
   voice · top-articles table. Invalid plan → deterministic default plan.
5. **Classification.** Per-article LLM extraction only for the fields the plan needs, cached by URL
   (re-runs are free and stable). Unknown stays "unknown". When Azure is unreachable, modules that need
   extraction are skipped and the page says so; modules computable from enriched fields still run.
6. **Compute.** Deterministic Python computes every chart / table value from rows + classifications.
   Peaks = top-5 periods by volume, each linked to its driving article.
7. **Insights.** LLM drafts 2–4 insight cards per RQ from the computed metrics + candidate articles. The
   validator (same rule as `llm_synthesis._grounded`) rejects any figure not in the metrics and any
   citation id not in that RQ's article set; uncited insights are dropped. Citation ids are global and
   resolve to URLs in the appendix.
8. **Template selection.** The 69 decks in `PPT Templates/` are indexed once (title + slide text;
   NVIDIA embeddings when configured, token-overlap otherwise) in SQLite. The scope (brand, category,
   brief) picks the closest deck; its master, cover and closing slides are inherited.
9. **Visual system.** Light backgrounds only (white + soft tint), palette from the client's Brandfetch
   colours blended with the category tone and contrast-checked; Hunter violet headings. Logos for the
   client and competitors via Brandfetch. Icons from Iconify (`circle-flags` for countries, a small
   line-icon set for themes / KPIs) rendered to PNG locally with Playwright (no cairosvg). Stock
   imagery: the category hero image already used on project pages (Pexels), credited.
10. **Render.** A generic deck builder on top of the existing `deliverable/blocks.py`:
    cover · agenda · executive summary (KPI tile per RQ answering it, with base) · share-of-coverage
    overview (doughnut + bar) · **per RQ**: trend line with labelled top-5 peaks, outlet bar chart,
    sentiment doughnut, entity / theme table, insight cards with citation chips, logos where brands
    appear · brand share of voice with logos · key takeaways (icon cards) · methodology (files, rows,
    dedup, base N, Boolean queries) · citation appendix · closing. Native editable PPTX charts with data
    labels; gauge / treemap rendered with amCharts 5 → PNG. The Word brief mirrors the sections.
11. **QC.** Geometry checks (text overflow, overlap, off-slide, dark backgrounds) plus PowerPoint COM PNG
    export; failures auto-fixed (shrink / reflow / split) and re-checked. A fact check confirms every
    figure on every slide exists in the computed metrics; the readiness score includes it.

## 4. Deliverables page (frontend)

- Stage timeline (Gate → Ingest → Routing → Plan → Classify → Compute → Insights → Template → Render → QC)
  with live status from `/ws`; reload restores the latest run.
- Sections stream in: data collection stats → per-RQ block (amCharts 5 charts drawn by one generic
  `ChartRenderer` from the stored chart spec, insight cards with clickable citation chips) → takeaways →
  slide thumbnails (from QC PNGs) → Download PPTX / DOCX.
- Chart specs come from the backend and are persisted, so the page and the PPTX show the same numbers.

## 5. Data model

- `intel_evidence`: add `url`, `document_id`, `source_file`, `row_index`.
- New: `intel_deliverable_runs` (status, stage, timings, output paths), `intel_deliverable_sections`
  (run_id, rq_id, kind, spec_json, data_json, insights_json), `intel_article_classifications`
  (url, field, value, evidence_span, model, created_at), `intel_reference_decks` (path, text, embedding).

## 6. Delivery in two phases (one spec, two plans)

- **Phase A — engine + visual deck.** Stages 1–11 backend, API (`POST /deliverable/{project_id}/run`,
  status, sections, downloads), Deliverables page gets a "Generate visual deck" action with stage
  progress and downloads. Acceptance: project 261 produces a visual deck end to end from the UI.
- **Phase B — streaming page.** amCharts in `web/`, `ChartRenderer`, streamed per-RQ sections,
  citation chips, thumbnails, timeline navigation.

## 7. Acceptance test — project 261

Inputs: 5 approved datasets (RQ1 225, RQ2 18, RQ3 70, RQ4 70, RQ5 482 rows). The deck must contain:
executive summary answering all five RQs with bases; per-RQ trend with top-5 peaks, outlets, sentiment,
entity table; expert type split and brand-affiliation share; celebrity names and roles; brand share of
voice with logos; takeaways with icons; methodology; citation appendix; every insight cited; light
backgrounds; QC and fact check clean.

## 8. Out of scope

Live Meltwater API · Postgres migration · in-product use of chat-only tools (Skywork, SlidesGPT, PPT MCP).

## 9. Decisions needed

- **amCharts licence:** the free build adds a small amCharts logo to every chart image and page chart.
- **Azure dependency:** classification and insight drafting need Azure OpenAI; without it those modules are
  skipped and labelled, not faked.
