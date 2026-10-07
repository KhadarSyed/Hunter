---
name: deck-studio
description: Build or refine a brand-led presentation (HTML deck + pixel-perfect PPTX/PDF) whose layouts are learned from a folder of reference decks. Use when the user wants a deck for research findings, wants to restyle or fix slides of a generated deck, or adds new reference decks. Fork of frontend-slides that follows the reference library's design rules instead of fixed style presets.
---

# Deck Studio

Turns structured findings into a presentation that looks like the decks in the reference folder (any
organisation's decks, not one house style), styled for the client's brand and the project's intent. It uses
the app's own renderer, guards and exporter, so a deck refined here matches what the app's Generate button
produces.

## Non-negotiables (kept from frontend-slides)

1. One self-contained HTML deck plus an `assets/` folder; every slide is one 1920x1080 stage and fits with no
   scrolling, no overflow and nothing off the slide.
2. Distinctive, brand-led design; never a generic template look.
3. Every number on a slide comes from the run's facts; research questions appear in full, never as codes like
   "RQ1"; no text is copied from a reference deck (only layout and style are reused).
4. Logos sit beside the label they belong to; photos follow chart density (A full-bleed for light slides, C photo
   panel for dense ones); no photo-credit text on slides.

## Workflow

1. **Find the material.**
   - For an app run: `python -m agent.app.domains.deckstudio.cli spec --run <run id>` prints the slide spec path.
   - Otherwise ask for the findings (questions, numbers, sources, brand) and write a spec JSON following
     `DESIGN_RULES.md` → Slide spec.
2. **Clarify only what is missing**, one question at a time: purpose and audience, the brand (colours, logo),
   the intent or mood the brand briefing implies, and anything the brief asked for that the material does not
   cover (it belongs on the checklist slide as Partial or Missing with a reason).
3. **Learn the references:** `cli index` (new or changed decks are picked up automatically), then
   `cli rules --family <family>`; choose the family the brief fits (topic map, audit, travel, brand social,
   follow-up).
4. **Art direction:** set `deck.tokens` from the brand colours and the intent (`DESIGN_RULES.md` → Tokens).
   Prefer the colours the brief or brand suggests; keep text contrast at least 4.5:1 and use fonts from the
   Google Fonts list.
5. **Edit the spec** for what the user asks: reorder slides, rewrite a so-what, switch a slide between A and C,
   change a photo query, add a slide of an existing type.
6. **Render:** `cli render --spec spec.json --out <dir>` (add `--no-creative` for template-only). The report
   says which slides kept their template version and why.
7. **Export:** `cli export --html <dir>/deck.html --spec spec.json --out <dir>` writes the `.pptx` and `.pdf`.
8. **Check before handing over:** open `deck.html`; confirm no overflow, every question in full, the
   "Did we answer the brief?" scorecard and the checklist present, every Partial or Missing row with a reason.
