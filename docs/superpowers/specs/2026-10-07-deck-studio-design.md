# Deck Studio — brand-led HTML deck + pixel-perfect PPTX from a reference-deck library

Date: 2026-10-07 · Status: draft for review · Phase 1 of 4

## 1. Why

The deliverable engine already computes correct, cited findings (charts, tables, insights, fact check). The
deck it produces is not good enough to send: it clones a client deck as a template (template names and
leftover art leak through), labels questions "RQ1", has no photography matching the slides, puts logos in a
corner instead of beside the labels they belong to, and never tells the client whether everything they asked
for was answered. The goal is a beautiful, brand-led presentation that meets every requirement of the brief,
in formats the team and the client can use.

## 2. Phases (each its own plan)

1. **This spec.** Reference-deck indexer, slide spec, art direction, assets, HTML deck, pixel-perfect PPTX +
   PDF export, and a generic fork of the frontend-slides skill.
2. Editable / hybrid PPTX renderer: native text, charts and tables over rendered backgrounds, from the same
   slide spec.
3. Remotion video of the findings, from the same slide spec.
4. Retire the classic python-pptx deck once phase 2 matches it.

## 3. Decisions taken with the user

| Topic | Decision |
|---|---|
| Output order | HTML deck first, then pixel-perfect PPTX/PDF from it; editable PPTX and video later |
| Templates | Slide-type library across ALL reference decks; new or changed decks are picked up automatically; one slide may borrow its layout from deck X while another borrows from deck Y |
| Generic | Nothing is Hunter-specific in code or skill: design rules are learned from whatever decks are in the reference folder (`config.TEMPLATES_DIR`, today `D:\HunterAgent\PPT Templates`) |
| Look | Fully brand-led: the LLM sets palette, typography and mood from the brand (Brandfetch) and the project intent; the agency wordmark appears on cover and closing only |
| Photos on content slides | Chosen by chart density: **A** full-bleed photo + brand-tinted overlay + frosted chart panel for light slides; **C** full-height photo panel (left ~35%) for dense slides |
| Photo sources | Licensed (Pexels/Unsplash) and brand-owned (Brandfetch banners, brand newsroom via Scrapling) first; SerpAPI + Playwright best match as fallback (licensing risk accepted); no credit text on slides, source recorded in the run log |
| Logos | Beside the label they belong to (bar labels, legend entries, column heads) |
| Questions | Full question text everywhere; never "RQ1" on a slide |
| Closing | "Did we answer the brief?" scorecard (A-style), then the full checklist table (paginated) |
| Build approach | Reference-library engine with per-slide-type templates **plus** an LLM creative pass per slide, kept only if it passes the guard checks (else the template version ships) |
| Skill | Both: the app's Generate button runs it automatically, and a generic "deck-studio" skill (fork of frontend-slides) refines decks interactively in Claude Code, reading the same rules and spec |

## 4. What the reference decks teach (input to the indexer)

From 68 decks (design report in the brainstorm notes): one 16:9 grid (13.333 × 7.5 in); header with the
title/question on the left and the "so-what" insight on the right; N = base label top-right of the chart
area; source footer `SOURCE: <TOOL> | <PERIOD>`; serif titles over sans body; signature slides — share-of-voice
doughnut + smoothed trend, gradient bar charts with theme cards, KPI strip dashboards, sentiment doughnut with
positive/negative panels, verbatim walls, person cards, comparison tables; full-bleed photography on covers,
contents and dividers; five families (topic map, audit master, travel/7Cs, brand-themed social, follow-ups).
Objective & Scope slides list the client's questions in full. No reference deck has a brief checklist.

## 5. Components (`agent/app/domains/deckstudio/`)

### 5.1 Indexer (`indexer.py`)
- Scans `config.TEMPLATES_DIR` for `*.pptx` (skips `~$*`, files over 50 MB such as the combined 200 MB+
  decks, unreadable files). A deck is re-indexed when its content hash changes; removed decks drop out.
- Per slide: renders a PNG (PowerPoint COM; skipped gracefully when unavailable), extracts geometry, text
  roles (kicker, title, so-what, body, footer), chart types and counts, tables, picture coverage (full-bleed,
  band, panel, tiles), fonts and colours.
- Classifies each slide into a **slide type** (cover, contents, objectives, divider, kpi_dashboard,
  sov_doughnut_trend, bar_with_cards, trend_with_peaks, sentiment_split, theme_cards, verbatim_wall,
  person_cards, comparison_table, takeaways, appendix_list, closing, other) — rules first, LLM vision on the
  PNG only for ambiguous slides.
- Clusters decks into families and stores **design rules** per family (grid, margins, type scale, header and
  footer pattern, chart conventions) as JSON.
- Storage: new tables `deck_reference_decks` (path, hash, family, indexed_at), `deck_reference_slides`
  (deck, n, type, features JSON, png path, embedding) — added by a new migration in `core/db.py`.
- Never copies text from a reference slide into output; only geometry and style patterns are reused.

### 5.2 Planner (`planner.py`) → slide spec
- Input: the engine's output (questions, sections, facts, insights, citations, executive answers) plus the
  brief's `expected_analyses` and `deliverables` from the research spec.
- Picks a family for the project (scope + brief text vs family profiles; reason written to the log), then for
  each needed slide the best slide type and reference example from any deck.
- Sequence: cover → objectives & scope (full questions, brands, sources, geography, period) → executive
  summary → per question: divider (A) + evidence slides → takeaways → "Did we answer the brief?" scorecard
  → checklist table pages → methodology → citations → closing.
- Treatment per slide by chart density: A for KPI, doughnut, ≤ 6 bars, dividers, takeaways, scorecard; C for
  trendlines, > 6 bars, tables, verbatim walls.
- **Brief checklist**: every research question + every expected analysis + every requested deliverable,
  matched to the slides that answer it, marked Covered / Partial / Missing with a one-line reason drawn from
  the engine (e.g. "No platform field in dataset", "Affiliation not stated in coverage"). Matching is LLM-
  assisted, with a deterministic fallback on keywords and module names.
- Slide spec schema (JSON, versioned): `{version, deck: {title, subtitle, period, base_n, family, tokens},
  slides: [{id, type, treatment, kicker, title, question, so_what, n_label, charts[], tables[], cards[],
  logos[], image: {query, role}, facts_allowed[], citations[], notes}]}`.

### 5.3 Art director (`art_director.py`)
- LLM call with the brand's Brandfetch colours, logo palette, the brief's intent and the chosen family's
  rules; returns design tokens: background, surface, primary, accent, chart series (6), overlay gradient,
  text colours, title and body fonts (Google Fonts), mood keywords for image search.
- Guards: WCAG contrast ≥ 4.5 for text, chart series distinguishable; deterministic fallback palette from the
  brand colours when the LLM is unavailable.

### 5.4 Asset finder (`assets.py`)
- Photos per slide from the image query: Pexels/Unsplash and brand-owned images first, then SerpAPI Google
  Images (Playwright/Scrapling to fetch full size); scored by relevance (LLM on titles/alt text), resolution
  (≥ 1600 px wide for A), and freshness; smart-cropped to the treatment. One image never repeats in a deck.
- Logos via Brandfetch (existing), favicons for sources (existing), flags (circle-flags), icons (Iconify).
- Every chosen asset's source URL and licence class are written to the run log; no credit text on slides.

### 5.5 Renderer (`renderer.py`, `templates/`)
- Jinja2 templates per slide type, built on frontend-slides' viewport-safe base (one self-contained HTML
  file, CSS custom properties from the design tokens, keyboard/scroll navigation, reduced-motion support).
- Charts: amCharts 5 (already a dependency) with readable axes (label skipping, rotation, truncation), peak
  annotations and logos beside category labels.
- **Creative pass**: per slide, the LLM receives the template HTML, the tokens, the reference slide's PNG
  description and the allowed facts, and may rewrite layout/CSS for that slide. The result is kept only if
  the guards pass:
  1. every number in the rendered text is in `facts_allowed` (existing fact checker, rounding rules kept);
  2. Playwright render at 1920 × 1080 has no scroll, no element outside the slide, no text overflow, no
     overlapping text boxes;
  3. no text from any reference deck appears (n-gram check against the indexed slide text).
  Failing slides fall back to the template version; the log says which and why.

### 5.6 Exporter (`exporter.py`)
- Playwright renders each slide at 1920 × 1080 → PNG; builds a 16:9 PPTX with one full-slide picture per
  slide, slide titles set as hidden slide titles and the full slide text in speaker notes (searchable,
  accessible); a PDF from the same PNGs. Downloads: `.html`, `.pptx`, `.pdf` beside the existing outputs.

### 5.7 Skill (`deck-studio`, fork of frontend-slides)
- Lives in the repo (`.claude/skills/deck-studio/`), generic: reads design rules from the indexer's JSON
  and the slide spec of a run (or builds a spec from pasted content), asks clarifying questions about intent,
  audience and brand when they are missing, then renders through the same renderer and guards. Keeps
  frontend-slides' non-negotiables (zero dependencies, viewport fit, distinctive design) and replaces its
  style presets with tokens from the art director.

## 6. Engine and UI integration
- New stages after `insights`: `index` (only when the library is stale), `plan`, `art`, `assets`, `render`,
  `export`, each reporting progress and log lines through the existing `_Run` (weights rebalanced so the
  overall % stays honest). The classic deck renders alongside until phase 4.
- Deliverables page: a deck preview (iframe of the HTML deck, slide thumbnails), downloads for
  HTML / PPTX / PDF, the template family and reference decks used and why, and the brief checklist summary.

## 7. Errors and degraded modes
- No LLM: deterministic planner, palette from brand colours, no creative pass — the deck still ships.
- No network: cached/brand images or tasteful gradient backgrounds from the tokens; logos fall back to text.
- No PowerPoint COM: indexer skips PNG rendering and classifies from geometry only.
- Reference folder empty: built-in neutral design rules.
- Any slide failing all checks: template version; if the template itself fails, the slide is flagged in QC.

## 8. Testing and acceptance
- Unit tests per component (indexer classification on fixture decks, planner sequence and treatment rules,
  checklist matching, token contrast, asset scoring and no-repeat, guard checks, exporter slide count).
- Acceptance on project 261: every slide fits 1920 × 1080 with no overflow; no "RQ" codes and no reference
  deck text on any slide; every question appears in full; every brand in a chart has its logo beside its
  label where Brandfetch has one; A/C photos on content slides, full-bleed cover/dividers/closing; the
  scorecard and checklist exist and every Missing/Partial row has a reason; fact check clean; PPTX and PDF
  slide counts equal the HTML slide count; a new deck dropped into the folder is indexed on the next run.

## 9. Out of scope (later phases)
Editable/hybrid PPTX (phase 2), Remotion video (phase 3), removing the classic deck (phase 4).
