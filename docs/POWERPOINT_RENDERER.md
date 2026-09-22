# PowerPoint Renderer — Architecture & Reference

*Stage 11 of the Hunter Intelligence pipeline.*

---

## Overview

The PowerPoint Renderer transforms an **approved Presentation Model** (produced by the Presentation Composer, Stage 10) into a branded `.pptx` file. It makes **zero** strategic or editorial decisions — all content decisions were already made by the Presentation Composer. The renderer is responsible only for faithful visual rendering.

**Input:** Approved Presentation (from `intel_pc_presentations` + `intel_pc_slides`)
**Output:** Valid `.pptx` file in `agent/data/rendered/`

---

## Rendering Pipeline

```
Approved Presentation Model
    │
    ├── validate_for_render()    → issues / warnings
    │
    ├── render_presentation()    → full deck
    │   ├── Resolve theme (hunter_default or custom)
    │   ├── Create blank presentation (13.333" × 7.5")
    │   ├── For each slide (ordered by slide_number):
    │   │   ├── PURPOSE_RENDERERS dispatch (cover/agenda/conclusion/appendix/divider)
    │   │   └── _render_content_slide() for all other purposes
    │   │       ├── Eyebrow label (purpose)
    │   │       ├── Title + takeaway
    │   │       ├── Visual dispatch (VISUAL_RENDERERS → 20 types)
    │   │       ├── Body text / bullets / quotes
    │   │       ├── Source footer + slide number
    │   │       └── Speaker notes
    │   ├── Record per-slide metrics
    │   ├── Save .pptx to rendered/ directory
    │   └── Create render job + rendered presentation + history records
    │
    ├── render_slide()           → single slide preview
    └── render_section()         → slides filtered by purpose
```

**Error recovery:** If a single slide fails to render, the pipeline catches the exception, logs a warning, inserts a placeholder error slide, and continues. The entire render does not fail.

---

## Theme Engine

Themes are stored in `intel_themes` and resolved at render time.

| Field | Default (hunter_default) |
|-------|--------------------------|
| `primary_color` | `#5B2C9D` (Hunter violet) |
| `secondary_color` | `#5E35B1` (Brand violet) |
| `accent_color` | `#A6CAEC` (Blue) |
| `background_color` | `#FFFFFF` |
| `text_color` | `#1A1A1A` |
| `font_heading` | Calibri |
| `font_body` | Calibri |
| `font_size_title` | 26pt |
| `font_size_body` | 14pt |
| `font_size_caption` | 9pt |

**Series palette (charts):** `[#5E35B1, #156082, #A02B93, #4EA72E, #196B24, #DE2A00, #A6CAEC, #D1C4E9]`

Custom themes can be created via `store.create_theme()` and selected at render time.

---

## Layout Engine

Three region sets define placeholder positions for different slide types:

**REGION_CONTENT** (standard content slides):
- `eyebrow` — purpose label, top-left
- `title` — slide title, below eyebrow
- `takeaway` — key message, top-right
- `body` — full-width body area
- `body_left` / `body_right` — split body
- `chart` — full-width chart area
- `chart_left` / `chart_right` — chart + narrative split
- `footer` / `source` / `slide_number` — bottom band

**REGION_COVER** — centered title/subtitle/date for cover slides
**REGION_DIVIDER** — centered title/subtitle for section dividers

All regions are 4-tuples: `(left_inches, top_inches, width_inches, height_inches)`.

---

## Chart Engine

Supported chart types rendered via `python-pptx`:

| Visual Type | Chart Type | Notes |
|-------------|-----------|-------|
| `bar_chart` / `grouped_bar` | `COLUMN_CLUSTERED` | Series palette applied |
| `stacked_bar` / `sankey` | `COLUMN_STACKED` | Multi-series |
| `line_chart` | `LINE_MARKERS` | Smooth line, 2pt |
| `pie` | `PIE` | Data labels with percentages |
| `donut` | `DOUGHNUT` | Data labels with percentages |
| `area` | `AREA` | Filled area chart |
| `scatter` | `XY_SCATTER` | Point-based, XY data |
| `bubble` | `BUBBLE` | 3D data (x, y, size) |
| `treemap` | `COLUMN_CLUSTERED` | Approximated as bar chart |

**Data extraction:** Content blocks are parsed for chart data. Metrics blocks are split on `:` to create categories and values. If no structured data is found, fallback placeholder data ensures charts always render.

---

## Additional Visual Renderers

| Visual Type | Rendering Approach |
|-------------|-------------------|
| `table` | Native PowerPoint table with header row, alternating row colors |
| `kpi_cards` | Colored rectangle tiles with value + label text boxes |
| `timeline` | Horizontal line with dot markers and date/label pairs |
| `funnel` | Narrowing rectangular stages with value labels |
| `network` / `theme_cluster` | Circular node layout with labels |
| `matrix` / `heatmap` | Delegates to table renderer |
| `map` | Placeholder with region labels (no geographic rendering) |
| `dashboard` | Combined KPI cards + chart |
| `quote` | Large italic centered text |

---

## Text Engine

- **Textbox creation:** `_add_textbox()` with font size, bold, italic, color, alignment, word wrap
- **Eyebrow labels:** Purpose text in uppercase, brand violet, 8pt
- **Slide titles:** Bold, 22pt, dark text
- **Takeaway:** Key message in muted grey, 11pt, right-aligned
- **Body text:** Paragraph list with configurable font size and region
- **Bullet list:** Prefixed with `•`, indented
- **Speaker notes:** Added to slide notes pane
- **Source footer:** Grey italic, bottom of slide

---

## Branding

The renderer uses the Hunter PR brand system:

- **Primary violet:** `#5B2C9D`
- **Brand violet (charts):** `#5E35B1`
- **8-color series palette** for chart data series
- **Cover slides:** Violet background, white text
- **Divider slides:** Violet background with section title
- **Agenda slides:** Numbered agenda items from content slide purposes
- **Slide numbering:** Bottom-right, grey text
- **Appendix slides:** Simple title + appendix marker

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `intel_render_jobs` | Render job tracking (status, progress, output path) |
| `intel_rendered_presentations` | Rendered output metadata (version, size, duration) |
| `intel_render_metrics` | Per-slide timing and warnings |
| `intel_themes` | Theme definitions (colors, fonts, sizes) |
| `intel_template_versions` | Template version history |
| `intel_render_history` | Render history audit trail |

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/renderer/render` | POST | Render full presentation |
| `/renderer/render-slide/{slide_id}` | POST | Render single slide |
| `/renderer/render-section/{pres_id}` | POST | Render slides by purpose |
| `/renderer/status/{job_id}` | GET | Render job status |
| `/renderer/download/{job_id}` | GET | Download .pptx file |
| `/renderer/themes` | GET | List available themes |
| `/renderer/validate/{pres_id}` | POST | Validate presentation for rendering |
| `/renderer/summary/{pres_id}` | GET | Render summary stats |
| `/renderer/jobs/{pres_id}` | GET | List render jobs |
| `/renderer/history/{pres_id}` | GET | Render history |
| `/renderer/metrics/{job_id}` | GET | Per-slide render metrics |

---

## Known Limitations

1. **Map visual is a placeholder.** No geographic rendering — shows a region list in a text box.
2. **Treemap and Sankey are approximated.** Treemap renders as a bar chart; Sankey renders as a stacked bar.
3. **No image embedding.** Screenshots, logos, and illustrations are not rendered. The architecture supports future image hooks.
4. **No slide thumbnails.** Preview is metadata-only in the frontend. COM-based thumbnail generation is not wired.
5. **Single template format.** All slides use a blank layout with programmatic positioning. Master slide layouts from hunter_template.pptx are not used.
6. **Chart formatting is basic.** No conditional formatting, data callouts, or annotations beyond legend and data labels.
7. **No PDF or Google Slides export.** Architecture supports future export formats but only .pptx is implemented.
8. **Font availability depends on host.** Calibri is specified but rendering depends on the font being installed on the machine opening the .pptx.
