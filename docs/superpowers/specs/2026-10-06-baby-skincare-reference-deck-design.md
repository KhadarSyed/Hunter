# Baby Skincare Category — Reference Deck Design

**Date:** 2026-10-06
**Status:** Design approved in chat; spec awaiting review
**Purpose:** Produce one hand-orchestrated, client-grade deck for the Baby Skincare brief. It is the
"golden" target that the automated Deliverable pipeline (draft spec:
`2026-10-06-streaming-deliverable-engine-design.md`) must reproduce.

## 1. Inputs

| Input | Location |
|---|---|
| Client brief | `Baby-Skincare_Category/Baby-Skin_Category_Brief.docx` |
| Celebrity-led coverage | `Baby-Skin_Category_Celebrity_Led_Coverage.xlsx` — 482 rows, 468 unique URLs, Oct 2025–Sep 2026, has Meltwater sentiment |
| Deal-led coverage | `Baby-Skin_Category_Deal_Led_Coverage.csv` — 225 rows/URLs, Jan–Aug 2026, CP1252 encoding, `DD-MM-YYYY` dates |
| Expert-citation coverage | `Baby-Skin_Category_Experts_Citations_Led_Coverage.xlsx` — sheets `MW_Extracted_Data` (49, full text) + `Manual_Extracted_Data` (21, full text); 69 unique URLs; no sentiment |
| Parenting-advice coverage | `Baby-Skin_Category_Parental Advice_Led_Coverage.xlsx` — 18 rows (Article, Link, Date, outlet in unnamed column), mixed date formats |
| Reference style | `PPT Templates/Hunter PR Research_Johnson's (Baby) Editorial _May 2026.pptx` (primary) and `…Johnson's (Baby) _May 2026.pptx` |

Brief questions (earned editorial, US, Oct 2025–Oct 2026):
1. Share of category coverage that is deal/sale-led.
2. Share focused on parenting advice.
3. Share citing experts; most-cited expert types (dermatologist, pediatrician, other HCP); % of cited experts affiliated with a brand.
4. Share that is celebrity-led or features celebrities.

## 2. Measurement base (decided)

- **Base = union of the four files, de-duplicated by normalised URL = 778 articles.**
- Theme shares are `theme_unique_urls / 778`. Two articles fall in two themes, so shares sum to slightly over 100%; this is stated on the slide.
- Every share slide carries the base line: *"Share of collected category coverage (N=778 unique articles, Meltwater + manual extraction, Oct 2025–Oct 2026)."*
- Method caveat (appendix + exec summary footnote): shares reflect the collected theme exports, whose breadth depends on each export's query; they are not a census of all category coverage.
- Window caveat: themes cover different date ranges (deal-led Jan–Aug 2026 only). Trend slides show each theme's actual range and never imply a common window.

## 3. Analysis

**Deterministic (computed from rows, never by an LLM):** counts, shares, monthly volumes, top-5 monthly peaks per theme, outlet rankings, sentiment splits (where Meltwater sentiment exists), reach sums.

**LLM classification (Azure OpenAI, per article, grounded on title + text):**
- Expert-led: expert name, expert type (`dermatologist` / `pediatrician` / `other_hcp` / `non_hcp_expert`), brand affiliation (`affiliated` + brand / `independent` / `unknown`) with the supporting quote span.
- Celebrity-led: celebrity names, celebrity role (spokesperson / product mention / lifestyle), brands mentioned.
- Deal-led: brand and product promoted, retailer, deal type (discount / freebie / bundle).
- Parenting-advice: advice topic (sun safety, eczema/dryness, bathing, diapering, ingredients…).
- Each classification stores the article URL; unclassifiable → `unknown`, never guessed. If Azure is unreachable, the build stops and reports it rather than substituting invented labels.

**Citations:** every insight sentence carries numbered citations `[n]` that map to article URLs in the appendix citation list; the numbering is global across the deck. An insight with no supporting article is cut.

## 4. Slide outline (17 slides, 16:9)

| # | Slide | Visuals |
|---|---|---|
| 1 | Cover — *Baby Skincare Category: Earned Editorial Analysis*, Oct 2025–Oct 2026 | Hunter cover artwork |
| 2 | Table of contents | — |
| 3 | Objective & scope — brief questions, US, Meltwater + manual extraction, base N=778, method notes | — |
| 4 | Executive summary — 4 KPI tiles (% deal, % parenting, % expert, % celebrity), one-line answer per brief question | KPI tiles |
| 5 | Coverage mix | Doughnut (share by theme) + monthly stacked column by theme, top-5 peaks highlighted and labelled |
| 6 | Deal-led coverage | Line trend with top-5 peaks; top outlets bar; brands/products promoted bar; insight cards with citations |
| 7 | Parenting advice | Topic table with outlet + citation; flagged small sample (n=18) |
| 8 | Expert-led: who is cited | Doughnut by expert type; % brand-affiliated (gauge, amCharts); top outlets |
| 9 | Expert-led: named experts | Table — expert, type, affiliation, outlet, citation |
| 10 | Celebrity-led: volume & sentiment | Line trend with top-5 peaks; sentiment doughnut |
| 11 | Celebrity-led: drivers | Top celebrities bar; positive vs negative driver cards with citations |
| 12 | Brands in the conversation | Share of brand mentions bar with Brandfetch logos |
| 13 | Key takeaways | Hunter takeaway card grid |
| 14 | Implications — consumer intent, messaging, whitespace | Cards |
| 15 | Appendix — definitions & methodology | — |
| 16 | Appendix — citation list `[n] outlet, date, headline, URL` (spills to extra slides if needed) | Table |
| 17 | Thank you | Hunter closing slide |

## 5. Visual system

- **Light only.** White canvas; header band uses a soft warm tint (cream/blush, e.g. `#FFF6F1`) in place of the reference deck's grey `#F2F2F2`. No dark or grey backgrounds.
- Hunter violet `#5B2C9D` for kickers/titles; body text near-black for contrast.
- Baby-care chart palette: lavender, peach, powder blue, mint (final hex values validated for ≥3:1 contrast against white for marks, ≥4.5:1 for text labels).
- All charts carry data labels; top-5 peaks get a distinct highlight colour and a callout naming the driving article(s) with citation.
- Footer on every content slide: `SOURCE: MELTWATER | <theme date range>` and the base N.

## 6. Build pipeline

1. Load + normalise the five sheets (encoding, date formats, URL normalisation, de-dup).
2. Deterministic metrics → JSON.
3. LLM classification → JSON (cached per URL so reruns are free and stable).
4. Insight drafting (LLM) constrained to the metrics JSON + classified articles; output includes citation ids; a validator rejects any number not present in the metrics JSON and any citation id not in the article set.
5. Deck assembly: open the Johnson's (Baby) Editorial deck as base via PPT MCP (`create_presentation_from_template`) to inherit master, fonts, cover and closing slides; rebuild content slides with python-pptx using the measured Hunter patterns; native editable charts for bar/line/doughnut; amCharts (rendered locally via Playwright to PNG) only for the gauge; logos via Brandfetch.
6. QC: export every slide to PNG through PowerPoint and review for overlaps, overflow, contrast and citation presence; fix and re-export until clean.

The build scripts are written as reusable modules so the Deliverable engine can absorb them later.

Output: `Baby-Skincare_Category/output/Hunter PR Research_Baby Skincare Category_Editorial_Oct 2026.pptx` plus the metrics/classification JSON beside it.

## 7. Out of scope

- Productising this flow (streaming Deliverable page, RQ-driven filtering, automatic reference-deck selection via embeddings) — draft spec `2026-10-06-streaming-deliverable-engine-design.md`.
- Track A UI fixes (citations on Background Research, Sample Eval removal, add-RQ, confidence threshold) — approved separately as a bounded change.
- Skywork / SlidesGPT — not used (no template support, cloud-hosted, chart limits).

## 8. Success criteria

- Every number on every slide reproduces from the metrics JSON.
- Every insight has ≥1 citation that resolves to a URL in the appendix.
- All four brief questions answered on the executive summary slide with the base stated.
- QC export shows no overlapping or overflowing elements and no dark/grey backgrounds.
