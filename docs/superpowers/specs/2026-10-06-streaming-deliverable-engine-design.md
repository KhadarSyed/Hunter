# Streaming Deliverable Engine — Design

**Date:** 2026-10-06
**Status:** DRAFT — not yet reviewed; follows the reference deck (see 2026-10-06-baby-skincare-reference-deck-design.md)
**Goal:** Hunter Agent itself turns an approved brief + RQs + uploaded Meltwater files into a
client-grade, cited, template-styled PPTX — streamed live on a single Deliverable page. No hand-built
decks. The Baby Skincare project is the acceptance test.

## 1. Why (current gaps, verified in code)

| Gap | Where |
|---|---|
| Execution uses only the first approved dataset file | `domains/execution/service.py:305` (`break`) |
| Analysis = 12 keyword/regex heuristics, no LLM, not consumer-intelligence grade | `methods/executors.py` |
| No charts anywhere in the UI; no chart library | `web/package.json` |
| Evidence has no URL / document id → insights cannot be cited | `intel_evidence` (`core/db.py:164`), `execution/repository.py:206` |
| Approval gate before execution is dead code | `validate_executor_prerequisites` (`execution/service.py:30`) never called |
| PPTX renderer starts from blank `Presentation()`; no template, no logos | `domains/rendering/pptx.py:1414` |

## 2. User flow

Brief → Scope (approve) → Search Strategy (approve; RQs + Meltwater queries; user can add RQs — Track A)
→ Data Sources (upload multiple files, enrichment, confidence-threshold review — Track A)
→ **Generate Deliverable** → **Deliverable page** streams everything → download PPTX.

The Research Plan / Research Execution / Analysis / Insights pages are removed from navigation; their
outputs appear as streamed sections on the Deliverable page.

## 3. Engine stages (backend, new `domains/deliverable/`)

Each stage persists its output and broadcasts progress on the existing `/ws` channel
(`deliverable_stage_started` / `deliverable_section_ready` / `deliverable_completed` / `deliverable_failed`).

1. **Gate.** Refuse to start unless scope, strategy and ≥1 dataset are approved (revive
   `validate_executor_prerequisites`).
2. **Ingest.** Load *every* approved file for the project (xlsx all sheets, csv with encoding fallback
   utf-8-sig → cp1252), normalise columns via the Meltwater column map, parse mixed date formats,
   normalise + de-duplicate by URL, keep `url`, `document_id`, `source_file`, `row_index` on every row.
   Rows marked irrelevant in review are excluded.
3. **RQ routing.** Each article is assigned to the RQs it matches:
   - rows from a file uploaded against an RQ belong to that RQ;
   - additionally each RQ's Meltwater Boolean query is evaluated locally (AND / OR / NOT, quoted
     phrases, parentheses, wildcard `*`; `NEAR/n` approximated as co-occurrence within n words)
     over title + opening text + hit sentence + full text.
   - Base N = unique articles across all RQs; every share is reported against it.
4. **Analysis planning (LLM chooses, engine computes).** For each RQ the LLM receives the RQ text,
   matched-row column profile and a fixed **module catalog**, and returns a JSON plan of modules +
   chart specs. It never returns numbers. Catalog (consumer-intelligence standard):
   share of coverage · volume trend with top-5 peak detection · sentiment split & drivers ·
   outlet/source-type ranking · reach & earned-value · theme/narrative clustering ·
   entity extraction (experts + type + brand affiliation, celebrities, brands, products, retailers) ·
   spokesperson/voice analysis · topic table · brand share of voice · whitespace (topics with demand
   but low brand presence).
   Plans are validated against the catalog schema; invalid → deterministic default plan per RQ.
5. **Classification.** Per-article LLM extraction only for the fields the plan needs, cached by URL
   (re-runs are free and stable). Unknown stays `unknown`. If Azure is unreachable, the stage fails
   visibly — no invented labels.
6. **Compute.** Deterministic pandas-free Python computes every value in every chart/table from rows +
   classifications. Peak detection = top-5 periods by volume, each linked to its driving articles.
7. **Insights.** LLM drafts insights per RQ from the computed metrics + candidate articles. A validator
   rejects any number not present in the metrics and any citation id not in the RQ's article set;
   insights without a valid citation are dropped. Citation ids are global and resolve to URLs.
8. **Reference deck selection.** The ~70 decks in `PPT Templates/` are indexed once (slide text +
   layout signature, NVIDIA embeddings stored in the existing SQLite slide index — no separate vector
   DB). The brief is embedded and the closest deck is chosen (Baby Skincare → Johnson's (Baby)
   Editorial). Its master, cover and closing slides are inherited; its content-slide patterns guide
   layout choice.
9. **Visual system.** Light backgrounds only (white + soft tint; no dark/grey). Palette derived from the
   client brand colours (Brandfetch) blended with a category tone; checked for contrast. Hunter violet
   for headings. Logos for client + competitors via Brandfetch (already integrated:
   `domains/research/brandfetch.py`).
10. **Render PPTX.** Upgrade `rendering/pptx.py` to build on the selected reference deck: Hunter
    header band + insight box, native editable charts with data labels and highlighted top-5 peaks,
    tables, takeaway card grid, appendix citation list, Boolean-query slide. Chart types native PPTX
    can't do (gauge, sankey, treemap, map) are rendered locally with amCharts 5 + Playwright to PNG.
11. **QC.** Export slides to PNG via PowerPoint COM; automated checks for text overflow, shape overlap,
    off-slide shapes, background luminance; failures are auto-fixed (shrink/reflow/split) and
    re-checked. QC report streamed to the page.

## 4. Deliverable page (frontend)

- Route `/:projectId/deliverable`; replaces Research Execution / Analysis / Insights in navigation.
- Stage timeline at top (Gate → Ingest → RQ routing → Plan → Classify → Compute → Insights →
  Template → Render → QC) with live status from `/ws`.
- Sections stream in as they're ready: data-collection stats (files, rows, de-dup, base N) →
  per-RQ block (amCharts 5 charts with labels + peak highlights, tables, insights with clickable
  citation chips) → key takeaways → deck preview thumbnails → **Download PPTX**.
- Chart rendering uses one generic `ChartRenderer` driven by the stored chart spec (the
  "LLM picks the spec, a component draws it" idea) — specs come from the backend, never from a
  browser-side LLM call, and are persisted so reloads and the PPTX show identical charts.
- amCharts 5 added to `web/` (MIT-licensed builds show a small logo unless licensed — confirm licence).

## 5. Data model additions

- `intel_evidence`: add `url`, `document_id`, `source_file`, `row_index`.
- New tables: `intel_deliverable_runs` (status, stage, timings), `intel_deliverable_sections`
  (run_id, rq_id, kind, spec_json, data_json, insights_json), `intel_article_classifications`
  (url, field, value, evidence_span, model, created_at), `intel_reference_decks` (path, embedding,
  layout signature).

## 6. Acceptance test — Baby Skincare

Inputs: `Baby-Skincare_Category/` brief + 4 files (5 sheets). RQs from the brief: deal-led share,
parenting-advice share, expert citation share + expert types + brand affiliation, celebrity-led share.

Expected (computed today by hand to validate the engine): base N = 778 unique articles
(celebrity 468, deal 225, expert 69, parenting 18; 2 overlap). The generated deck must contain:
exec summary answering all four questions with the base stated; per-RQ charts with top-5 peaks;
expert type split and brand-affiliation %; celebrity sentiment and drivers; brand share with logos;
takeaways; appendix citation list; every insight cited; light backgrounds; QC clean.

## 7. Out of scope

- Track A (citations on Background Research, Sample Eval removal, add-RQ, confidence threshold) —
  approved bounded change, built separately.
- Skywork / SlidesGPT / PPT MCP inside the product (they're chat tools, not backend libraries).
- Live Meltwater API (uploads only).
- Postgres migration (SQLite stays).

## 8. Open items

- amCharts licence (free build shows a logo).
- Azure OpenAI must be configured and reachable for stages 4, 5, 7; otherwise the run fails visibly.
