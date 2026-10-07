# Deck Studio design rules

## Slide spec (`agent/app/domains/deckstudio/spec.py`)

`DeckSpec`
- `version` — spec format version (1).
- `title`, `subtitle`, `period`, `base_n` — cover line, deck subtitle, data period, unique-article base.
- `family`, `family_reason` — reference family chosen and why.
- `tokens` — `DeckTokens` (below) or null before art direction.
- `slides` — ordered `SlideSpec` list.

`SlideSpec`
- `id` — stable id (`cover`, `objectives`, `executive-summary`, `<rq>-divider`, `<section id>-<i>`, `takeaways`,
  `scorecard`, `checklist-<k>`, `methodology`, `citations-<k>`, `closing`).
- `type` — slide type (cover, objectives, executive_summary, divider, kpi_dashboard, sentiment_split,
  trend_with_peaks, bar_with_cards, theme_cards, comparison_table, takeaways, scorecard, checklist,
  methodology, citations, closing).
- `treatment` — `full`, `A`, `C` or `plain` (see Treatment).
- `kicker`, `title`, `question`, `so_what`, `n_label` — on-slide text; `question` is the full research question.
- `charts` — `{kind, categories, values, unit, peaks}`; kinds `bar`, `line_peaks`, `column`, `doughnut`, `kpi`, `treemap`.
- `tables` — `{header, rows}`; `cards` — `{headline, text, note?, citations?}`.
- `logos` — category name → logo file; drawn beside that label.
- `image` — `{query, role, path}`; `role` is `background` (A/full) or `panel` (C).
- `facts_allowed` — the only sources of numbers for this slide.
- `citations`, `notes`, `reference` (`{deck, slide, why}` — the reference layout used).

## Tokens (`DeckTokens`)

`background`, `surface`, `primary`, `accent`, `text`, `muted`, `on_dark`, `series` (6 chart colours),
`overlay` (CSS gradient over photos), `title_font`, `body_font`, `mood` (photo-search words).
Guards: text and muted text ≥ 4.5:1 on the background; primary ≥ 3:1; fonts from: Inter, Nunito Sans,
Source Sans 3, Work Sans, DM Sans, Manrope, Lato, Montserrat, Poppins, Raleway, Playfair Display, Fraunces,
Lora, Merriweather, DM Serif Display, Libre Baskerville, Cormorant Garamond, Space Grotesk, Outfit, Quicksand.

## Treatment (by chart density)

- `full` — cover, question dividers, closing: full-bleed photo, brand overlay, large type.
- `A` — light slides (KPI, doughnut, up to 6 bars, executive summary, takeaways, scorecard): full-bleed photo,
  brand overlay, chart or cards on a frosted panel.
- `C` — dense slides (trendlines, more than 6 bars, tables): photo panel on the left 672 px, chart right.
- `plain` — checklist, methodology, citations.
- No photo found: a gradient from the brand tokens, never an empty box.

## Slide sequence

Cover → Objectives & scope (every question in full; brands, sources, geography, period) → Executive summary →
per question: divider (question + headline answer) and its evidence slides → Key takeaways →
"Did we answer the brief?" scorecard → checklist pages → Definitions & methodology → Sources → Closing.

## What the reference decks teach

One 16:9 grid; header with the title or question on the left and the "so-what" on the right; `N = base` label
top-right of the chart area; source footer `SOURCE: <tool> | <period>`; serif titles over sans body; signature
slides: share-of-voice doughnut + smoothed trend, gradient bars with theme cards, KPI strip dashboards,
sentiment doughnut with positive/negative panels, verbatim walls, person cards, comparison tables; full-bleed
photography on covers, contents and dividers. Families: topic map (default), audit, travel / 7Cs, brand-themed
social, follow-up.
