# Slide Intelligence Guide

## Architecture

Slide Intelligence sits between the Storyline Builder and the future PowerPoint Generator:

```
Storyline Builder (approved narrative structure)
         ↓
Slide Intelligence (historical style reference)
         ↓
PowerPoint Generator (future sprint)
```

### Backend Services

| Service | File | Responsibility |
|---------|------|---------------|
| Slide Extractor | `slide_extractor.py` | PPT parsing, text extraction, shape detection, classification, project boundary detection, style analysis, template detection |
| Slide Retrieval | `slide_retrieval.py` | Semantic retrieval, similarity scoring, diversity-aware ranking, storyline matching, recommendation engine |
| Slide Intelligence | `slide_intelligence.py` | Orchestrator: ingestion, dashboard, search, duplicate detection, metadata management |
| Intelligence Store | `intelligence_store.py` | 11 new tables, 15 indexes, ~40 store functions |
| Intelligence API | `intelligence_api.py` | 22 REST endpoints |

### Database Schema (11 tables)

| Table | Purpose |
|-------|---------|
| `intel_si_presentations` | Uploaded presentation files |
| `intel_si_slides` | Individual slides with full metadata |
| `intel_si_template_families` | Detected template families |
| `intel_si_template_members` | Slides belonging to template families |
| `intel_si_detected_projects` | Probable project groupings |
| `intel_si_style_patterns` | Extracted style patterns |
| `intel_si_retrieval_history` | Retrieval query history |
| `intel_si_storyline_matches` | Storyline node → slide matches |
| `intel_si_processing_logs` | Processing pipeline logs |
| `intel_si_corrections` | Manual metadata corrections |
| `intel_si_embeddings` | Slide text embeddings |

---

## Processing Pipeline

### Ingestion Flow

1. **File validation** — verify file exists, compute MD5 hash, check for duplicates
2. **Presentation record** — create `intel_si_presentations` entry, set status to `processing`
3. **Per-slide extraction** (resumable):
   - Extract all text (title, body, footer, notes)
   - Count shapes, charts, tables, images
   - Detect chart types from python-pptx chart objects
   - Classify slide (purpose, layout, visual type, narrative role, report type)
   - Persist to `intel_si_slides`
4. **Project boundary detection** — identify cover slides using "Analyst / Client" title pattern
5. **Style analysis** — extract typography, footer, chart, and KPI patterns
6. **Template detection** — group slides by purpose + layout into families
7. **Completion** — set status to `completed` or `partial` (if any slides failed)

### Resumable Processing

If processing is interrupted, calling `process_presentation()` again with the same `presentation_id` will skip already-processed slides and continue from where it left off. The `processed_count` field tracks progress.

### Partial Failures

Individual slide failures do not block the pipeline. Failed slides are logged to `intel_si_processing_logs` with error details. The presentation status becomes `partial` if any slides failed.

---

## Metadata Model

### Slide Classification

Each slide is classified along multiple dimensions:

**Slide Purpose** (18 types):
cover, executive_summary, methodology, scope, key_finding, trend, theme, sentiment, competitive, consumer_insight, crisis, timeline, recommendation, opportunity, risk, conclusion, appendix, table_of_contents, divider, thank_you, other

**Layout Type** (16 types):
title_body, single_insight, two_column, three_column, dashboard, kpi_cards, comparison, timeline, matrix, heatmap, quote, chart_led, text_led, mixed, title_only, blank

**Visual Type** (21 types):
kpi, bar_chart, stacked_bar, line_chart, area_chart, pie, donut, heatmap, table, matrix, timeline, funnel, journey, quote, theme_cluster, screenshot, network, map, text_only, mixed_chart, none

**Narrative Role** (8 types):
context, evidence, finding, interpretation, business_impact, recommendation, transition, summary

**Report Type** (10 types):
crisis, reputation, campaign, consumer, brand_health, competitive, media_monitoring, social_listening, executive_briefing, new_business_pitch, unknown

**Additional**:
- Industry, Client, Brand (detected from project boundaries)
- Data Density: low / medium / high
- Executive Suitability: low / medium / high
- Visual Complexity: low / medium / high
- Classification Confidence: 0.0 to 1.0

### Classification Method

All classification is **deterministic** (no LLM calls). It uses keyword matching against the slide's title and body text with weighted scoring. The classifier checks keywords in priority order:

1. Structural slides first (cover, TOC, scope, methodology, appendix, thank you)
2. Topic-specific slides (crisis, competitive, sentiment, trend, consumer insight)
3. Content-based fallbacks (chart presence → key_finding, few shapes → divider)

---

## Retrieval Engine

### Similarity Scoring

Each slide is scored against a storyline node using multi-dimensional matching:

| Dimension | Weight | Method |
|-----------|--------|--------|
| Purpose match | 0.30 | Section type → preferred purposes lookup |
| Layout match | 0.15 | Section type → preferred layouts lookup |
| Visual type match | 0.10 + 0.10 | Section preferences + exact match with node's suggested visual |
| Text similarity | 0.25 | Keyword overlap (Jaccard coefficient) |
| Quality bonuses | 0.05 + 0.05 | Executive suitability + classification confidence |

### Diversity-Aware Ranking

The retrieval engine prevents returning 10 nearly identical slides by tracking:
- Purpose diversity (penalty after 2+ same-purpose slides)
- Layout diversity (penalty after 3+ same-layout slides)
- Client diversity (penalty after 3+ same-client slides)

### Section → Purpose Mapping

| Storyline Section | Preferred Slide Purposes |
|-------------------|-------------------------|
| executive_summary | executive_summary, key_finding |
| key_findings | key_finding, trend, sentiment |
| supporting_evidence | key_finding, trend, consumer_insight |
| emerging_themes | trend, theme, consumer_insight |
| risks | risk, crisis |
| opportunities | opportunity, trend |
| competitive_perspective | competitive |
| recommendations | recommendation |
| conclusion | conclusion, executive_summary |

---

## Template Families

### Detection Method

Slides are grouped into template families by their `purpose + layout` combination. Only groups with 2+ members become families. The slide with the highest classification confidence is marked as the representative.

### Family Properties

- Family name (auto-generated from purpose, e.g., "Key Finding (Chart Led)")
- Typical layout, visual type, and purpose
- Required inputs (JSON array)
- Recommended usage text
- Member count
- Approval status (analyst can approve families for use in recommendations)

---

## Storyline Integration

### Matching Flow

1. For each node in an approved storyline, retrieve top-5 historical slides
2. Store matches in `intel_si_storyline_matches` with:
   - Similarity score
   - Match reason (human-readable)
   - Recommended elements to reuse (layout, chart type, visual hierarchy)
   - Elements NOT to reuse (historical data, client branding, source citations)
3. Group results by node for presentation

### Recommendation Output

For each storyline node, the recommendation engine provides:
- Best layout type
- Best visual type
- Best chart type (from historical data)
- Content hierarchy (ordered list of content elements)
- Callout style recommendation
- Evidence placement guidance
- Title style guidance
- Alternative layout options
- Historical slide references

---

## Content Safety

**Historical slides are ONLY presentation style references.**

They must NEVER:
- Become research evidence for new reports
- Support new factual claims
- Influence the Insight Generator or Evidence Library
- Be reused as-is in new presentations (only their style can inform new slides)

The Evidence Library and Slide Intelligence are completely separated in the database schema — there are no foreign key relationships between them.

Elements safe to reference from historical slides:
- Layout structure and spacing
- Chart types and placement
- Visual hierarchy patterns
- Title and headline conventions
- Footer formatting
- Color usage patterns

Elements that must NOT be reused:
- Historical data points and statistics
- Client-specific content and branding
- Source citations from past research
- Specific findings or conclusions

---

## Manual Review Workflow

1. **Browse** slides in the Library tab with filters (purpose, layout, client, search)
2. **Review** individual slides in the detail drawer
3. **Correct** metadata using the edit form (tracked in `intel_si_corrections`)
4. **Exclude** irrelevant slides from retrieval
5. **Reprocess** slides if the source presentation has been updated
6. **Approve** template families for use in storyline recommendations

---

## Known Limitations

1. **No image-based thumbnails.** Slide previews are text-based metadata only. Full thumbnail generation via PowerPoint COM is supported but not yet wired into the pipeline.

2. **No embedding-based retrieval.** Text embeddings via Ollama `nomic-embed-text` are supported in the schema but the pipeline currently uses keyword-overlap similarity. Embedding generation for 1000+ slides would take significant time on CPU.

3. **Classification is keyword-based.** No LLM is used for classification, which means nuanced slide purposes may be misclassified. Manual corrections are supported.

4. **Project boundary detection relies on title patterns.** The "Analyst / Client" pattern works for Hunter PR's deck format but may not generalize to other formats.

5. **No cross-presentation deduplication.** Duplicate detection currently operates within a single presentation. Cross-presentation deduplication could be added.

6. **Style analysis is statistical.** Font names, exact colors, and precise positioning are not extracted (python-pptx has limited access to theme colors and font rendering).
