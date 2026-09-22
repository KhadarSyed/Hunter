# Word Report Renderer

Transforms an approved Presentation Model into a professionally formatted Microsoft Word (.docx) report using python-docx. This is a pure rendering engine — it never regenerates content, rewrites insights, modifies evidence, changes storyline, or reorders sections. If the Presentation Model is incomplete, validation fails with descriptive errors.

## Architecture

### Responsibilities

- Validate presentation model completeness before rendering
- Resolve document themes (fonts, colors, sizing)
- Render structured sections from Presentation Model slides
- Generate styled tables from chart/table content blocks
- Manage citations and evidence references with footnotes
- Track per-section render metrics and audit history
- Produce downloadable .docx files

### Document Structure

| # | Section | Source | Always Present |
|---|---------|--------|----------------|
| 1 | Cover Page | Cover slide or presentation title | Yes |
| 2 | Confidentiality Notice | Static template | Yes |
| 3 | Table of Contents | Auto-generated (Word field code) | Yes |
| 4 | Executive Summary | Executive summary slides + presentation summary | Yes |
| 5 | Methodology | Methodology slides or default text | Yes |
| 6 | Key Findings | Slides with purposes: key_finding, trend, consumer_insight, sentiment, competitive, crisis, content | Conditional |
| 7 | Sources & Evidence | Collected evidence panel footnotes | Conditional |
| 8 | Business Impact | Slides with purposes: opportunity, risk | Conditional |
| 9 | Recommendations | Recommendation slides | Conditional |
| 10 | Conclusion | Conclusion slides | Conditional |
| 11 | Appendix | Appendix slides | Conditional |

### Slide Purpose Mapping

Presentation Model slides are routed to document sections based on their `slide_purpose`:

| Slide Purpose | Document Section |
|---------------|-----------------|
| cover | Cover Page |
| agenda, executive_summary | Executive Summary |
| methodology | Methodology |
| key_finding, trend, consumer_insight, sentiment, competitive, crisis, content | Key Findings |
| opportunity, risk | Business Impact |
| recommendation | Recommendations |
| conclusion | Conclusion |
| appendix | Appendix |
| divider | Skipped |

## Style Engine

### Heading Hierarchy

| Level | Font Size | Usage |
|-------|-----------|-------|
| Heading 1 | 24pt | Major sections (Executive Summary, Key Findings, etc.) |
| Heading 2 | 18pt | Sub-sections (individual findings, recommendations) |
| Heading 3 | 14pt | Content block titles |
| Heading 4-6 | 12pt | Reserved for deep nesting |

All headings use the theme's heading font (default: Calibri), bold, in the primary brand color.

### Paragraph Styles

- Body text: theme body font, theme body size (default 11pt), 1.15 line spacing, 6pt after
- Captions: 9pt, italic, grey
- Callout boxes: white text on primary color background, centered, bold
- Quotes: italic, indented 1.5cm both sides, secondary color
- Bullets: Word's built-in "List Bullet" style

### Page Setup

- Margins: 2.54cm (1 inch) all sides
- Orientation: Portrait
- Headers: report title (right-aligned, 8pt)
- Footers: "CONFIDENTIAL" (centered, 7pt) + page numbers (right-aligned, 8pt)
- Different first page header/footer (cover page has no header)

## Table Engine

Tables are rendered with:
- Header row: primary color background, white bold text, 9pt
- Data rows: 9pt body font, alternating row shading (#F5F5F5)
- Table Grid style with center alignment
- Dynamic column count based on data

Input formats supported:
- `{"headers": [...], "rows": [[...], ...]}`
- `[{"col1": "val1", ...}, ...]` (list of dicts)
- `[[...], [...]]` (list of lists)
- `[val1, val2, ...]` (simple list → single-column table)

## Chart Engine

Charts from the Presentation Model are rendered as styled data tables (Word doesn't support native chart insertion via python-docx). Each chart includes:
- Figure caption with chart type label
- Category/series data in a styled table
- Support for single-series and multi-series data

Supported chart types (rendered as tables): bar, line, pie, donut, stacked_bar, area, scatter, radar, waterfall, funnel, gauge, treemap, heatmap, bubble, combo, histogram.

## Citation Manager

Evidence references are collected during rendering:
- Evidence panels create footnotes with superscript reference numbers
- Sources & Evidence section lists all footnotes with index, source text, and full text
- Evidence IDs from slides are tracked for cross-referencing

## Theme System

Themes are resolved from the existing `intel_themes` table:

| Property | Default |
|----------|---------|
| primary_color | 5B2C9D (Hunter violet) |
| secondary_color | 5E35B1 (Brand violet) |
| accent_color | 7C4DFF |
| background_color | FFFFFF |
| text_color | 333333 |
| font_heading | Calibri |
| font_body | Calibri |
| font_size_title | 28 |
| font_size_body | 11 |
| font_size_caption | 9 |

Theme resolution: requested theme → `hunter_default` → hardcoded fallback.

## Database Tables

| Table | Purpose |
|-------|---------|
| `intel_word_jobs` | Job tracking (id, presentation_id, job_type, status, progress, output_path, warnings, timing) |
| `intel_word_documents` | Rendered document records (version, path, size, section_count, word_count, theme, duration) |
| `intel_word_metrics` | Per-section render metrics (section_name, section_number, duration_ms, element_count) |
| `intel_word_history` | Audit trail (action, actor, details, timestamp) |

6 indexes for efficient querying by presentation_id, job status, and job_id.

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/word-renderer/render` | Render full Word report |
| POST | `/word-renderer/render-section/{pres_id}` | Render single section |
| POST | `/word-renderer/validate/{pres_id}` | Validate presentation for rendering |
| GET | `/word-renderer/status/{job_id}` | Get render job status |
| GET | `/word-renderer/download/{job_id}` | Download rendered .docx file |
| GET | `/word-renderer/themes` | List available themes |
| GET | `/word-renderer/summary/{pres_id}` | Render summary for presentation |
| GET | `/word-renderer/jobs/{pres_id}` | List all render jobs |
| GET | `/word-renderer/history/{pres_id}` | Render history audit trail |
| GET | `/word-renderer/metrics/{job_id}` | Per-section render metrics |

All endpoints are under the `/api/intel/` prefix.

## Frontend

The Word Renderer page (`WordRendererPage.tsx`) provides:
- Summary cards (total renders, total jobs, latest status, word count, download)
- Presentation and theme selectors
- Validate and Render Word Report buttons
- Validation result display (issues and warnings)
- Render result display with download button
- 4-tab layout: Sections / Metrics / History / Jobs
- Section grid with per-section render buttons (10 sections)
- Metrics table with per-section timing and element counts
- History table with timestamped actions
- Jobs table with status badges and download links

## Render Pipeline

1. **Validate** — check presentation exists, has slides, flag warnings
2. **Create job** — insert into `intel_word_jobs` with status "pending"
3. **Resolve theme** — load from `intel_themes` with fallback chain
4. **Create document** — initialize python-docx Document
5. **Setup styles** — configure Normal, Heading 1-6 styles
6. **Add metadata** — set document properties (author, title, subject)
7. **Add header/footer** — title header, confidentiality footer, page numbers
8. **Render sections** — iterate through sections in order, timing each:
   - Cover Page → Confidentiality → TOC → Executive Summary → Methodology → Key Findings → Sources & Evidence → Business Impact → Recommendations → Conclusion → Appendix
9. **Save file** — write to `data/rendered/` directory
10. **Record document** — insert into `intel_word_documents` with metrics
11. **Update job** — set status "completed" with output path and stats
12. **Log history** — audit trail entries for start and completion

## Tests

62 automated tests across 11 test classes:
- ValidationTest (6): missing presentation, valid with slides, no slides, no cover/conclusion warnings, rejected slides warning
- ThemeResolutionTest (5): default theme, unknown fallback, hex-to-RGB conversion (valid, with hash, invalid)
- RenderReportTest (7): full report, job+document creation, metrics, history, invalid presentation, rejected exclusion, version increment
- RenderSectionTest (5): single section, unknown section, cover, methodology, all valid sections
- StatusAndDownloadTest (4): render status, status not found, download path, download not found
- RenderSummaryTest (2): empty summary, summary after render
- ThemesListTest (1): list themes
- ContentBlockRenderingTest (4): content blocks, tables, charts, evidence panels
- WordStoreTest (7): create/get/update/list jobs, create/list documents, metrics, history
- SectionOrderTest (3): section count, key sections present, purpose mapping
- HelperFunctionTest (6): chart data extraction, evidence ref collection, valid types/statuses
- APIEndpointTest (13): all 11 endpoints tested including render+download integration

## Known Limitations

1. **No native chart embedding.** python-docx doesn't support inserting native Word charts. Charts are rendered as styled data tables with figure captions.
2. **TOC requires manual update.** The TOC field code is inserted but must be updated by opening the document in Word (right-click → "Update Field").
3. **No image embedding.** Slide images/logos are not embedded — the renderer handles text and data content only.
4. **No PDF export.** Word documents are .docx only. PDF conversion requires Word or LibreOffice.
5. **Page count not tracked.** python-docx cannot determine page count — only word count and section count are recorded.
