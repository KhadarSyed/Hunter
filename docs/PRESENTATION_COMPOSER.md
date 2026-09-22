# Presentation Composer — Architecture & Reference

## Overview

The Presentation Composer (Stage 10) transforms an approved storyline, approved insights, and accepted evidence into a structured **Presentation Model**. It is NOT a PowerPoint generator — it produces an internal data model that specifies what slides should exist, what each communicates, which layout and visual to use, which evidence supports each slide, and how the presentation flows.

## Prerequisites

Four gates must pass before generation:

| Gate | Check | Source |
|------|-------|--------|
| Storyline | Approved storyline exists for project | `intel_storylines.status = 'approved'` |
| Insights | At least 1 approved insight | `intel_insights.status = 'approved'` |
| Evidence | At least 1 accepted library item | `intel_library_items.review_status = 'accepted'` |
| SI Library | Slide Intelligence library is non-empty | `intel_si_slides` has rows |

## Slide Model

Each slide stores 20+ fields:

| Field | Type | Description |
|-------|------|-------------|
| id | int | Auto-increment primary key |
| presentation_id | int | FK to parent presentation |
| slide_number | int | Position in deck (0-based) |
| slide_purpose | string | One of 17 purpose types |
| node_id | int? | FK to storyline node (null for cover/agenda/conclusion) |
| title | string | Slide title |
| subtitle | string? | Optional subtitle |
| narrative | string? | Narrative text for the slide |
| business_objective | string? | What business question this slide answers |
| key_message | string? | The single most important takeaway |
| speaker_notes | string? | Generated speaker notes |
| recommended_visual | string? | One of 20 visual types |
| recommended_chart | string? | Specific chart subtype from SI |
| layout_recommendation | string? | Primary layout |
| layout_rationale | string? | Why this layout was chosen |
| alt_layout_1 | string? | First alternative layout |
| alt_layout_1_rationale | string? | Rationale for alt 1 |
| alt_layout_2 | string? | Second alternative layout |
| alt_layout_2_rationale | string? | Rationale for alt 2 |
| template_family_id | int? | FK to SI template family |
| content_blocks_json | json | Array of typed content blocks |
| evidence_ids_json | json | Array of evidence library item IDs |
| insight_ids_json | json | Array of insight IDs |
| historical_refs_json | json | Array of historical slide references |
| confidence_json | json | Multi-dimensional confidence scores |
| overall_confidence | float | Weighted overall confidence (0-1) |
| transition_to_next | string? | Flow transition text |
| status | string | draft / needs_review / approved / rejected |
| is_locked | int | 0 or 1 |

## 17 Slide Purposes

cover, agenda, executive_summary, context, methodology, key_finding, trend, theme, competitive, audience, sentiment, timeline, opportunity, risk, recommendation, conclusion, appendix

## 16 Content Block Types

title, subtitle, executive_summary, key_insight, narrative, evidence_panel, metrics, chart, callout, quote, verbatim, comparison, timeline, recommendation, footnote, source

## 20 Visual Types

bar_chart, stacked_bar, line_chart, area, scatter, bubble, heatmap, timeline, journey, matrix, table, network, treemap, sankey, quote, dashboard, kpi_cards, funnel, map, theme_cluster

## Layout Selection

For each content slide, the composer:

1. Retrieves SI recommendation for the storyline node (`recommend_for_node`)
2. Uses the SI-recommended layout as primary
3. Picks up to 2 alternative layouts from SI
4. Generates a rationale for each (referencing section type and historical usage)
5. Matches against SI template families for historical context

Users can switch layouts via the `select_layout` API.

## Visual Selection Cascade

```
1. SI recommended chart type (if valid)
2. SI recommended visual type (if not "text_only")
3. Purpose-default visual (from _PURPOSE_VISUAL_MAP)
4. Fallback: bar_chart (if evidence exists) or kpi_cards
```

## Confidence Scoring

Four weighted dimensions:

| Dimension | Weight | Calculation |
|-----------|--------|-------------|
| Evidence coverage | 0.30 | min(evidence_count / 3, 1.0); 0.3 if no evidence |
| Storyline coverage | 0.25 | min(insight_count / 2, 1.0); 0.3 if no insights |
| Historical layout match | 0.25 | best_similarity + 0.2 from SI; 0.3 if no match |
| Visual suitability | 0.20 | 0.8 for non-default visuals; 0.7 for kpi_cards; 0.5 otherwise |

Low confidence reasons are generated when evidence < 0.5 or historical match < 0.5.

## Presentation Flow

8 flow stages: opening, context, problem, supporting_evidence, insights, business_impact, recommendations, conclusion

Each slide purpose maps to a flow stage. Transitions between stages use templates (e.g., "insights" -> "business_impact" = "These insights carry clear business implications.").

## Generation Process

1. Validate prerequisites (4 gates)
2. Retrieve approved storyline and nodes
3. Build cover slide (slide 0)
4. Build agenda slide (slide 1)
5. For each storyline node:
   - Map section type to slide purpose
   - Get SI recommendation
   - Select layout (primary + 2 alternatives)
   - Select visual (cascade)
   - Build content blocks
   - Compute confidence
   - Gather evidence IDs from insight-evidence mappings
   - Persist slide with all fields
6. Build conclusion slide if no conclusion node exists
7. Update presentation totals
8. Create audit entry

## Database Schema

### intel_pc_presentations
Stores presentation metadata: project, storyline, title, summary, status, approval.

### intel_pc_slides
Stores individual slides with all 20+ fields. JSON fields serialized on write, deserialized on read.

### intel_pc_audit
Tracks all mutations: generation, slide updates, layout changes, visual changes, reviews, locks, reorders.

## API Endpoints (18 routes)

| Method | Path | Description |
|--------|------|-------------|
| POST | /composer/generate | Generate presentation |
| POST | /composer/validate-prereqs | Check prerequisites |
| GET | /composer/{project_id} | List presentations |
| GET | /composer/{project_id}/summary | Summary metrics |
| GET | /composer/detail/{pres_id} | Full detail with slides |
| GET | /composer/slides/{pres_id} | List slides |
| GET | /composer/slide/{slide_id} | Single slide |
| PUT | /composer/slide/{slide_id} | Update slide fields |
| POST | /composer/slide/{slide_id}/review | Approve/reject slide |
| POST | /composer/slide/{slide_id}/lock | Lock slide |
| POST | /composer/slide/{slide_id}/unlock | Unlock slide |
| POST | /composer/slide/{slide_id}/layout | Change layout |
| POST | /composer/slide/{slide_id}/visual | Change visual |
| POST | /composer/{pres_id}/reorder | Reorder slides |
| POST | /composer/{pres_id}/approve | Approve presentation |
| POST | /composer/{pres_id}/reject | Reject presentation |
| GET | /composer/{pres_id}/validate | Validate presentation |
| POST | /composer/{pres_id}/transitions | Generate transitions |
| GET | /composer/audit/{pres_id} | Audit trail |

## Known Limitations

- No LLM involvement: all decisions are deterministic, based on mappings and SI recommendations
- `_analyze_flow` maps slide purposes through `_SECTION_TO_FLOW_STAGE` (keyed by section type); the "problem" flow stage has no direct section mapping, so flow_complete may report false even when coverage is adequate
- Visual selection depends on SI having indexed relevant historical slides; empty SI library means purpose-default visuals only
- Content blocks are formulaic (title + narrative + insights + evidence panel); no LLM-generated copy
- Speaker notes are template-based, not context-aware
- No slide-to-slide dependency tracking (e.g., "this slide builds on slide 3")
