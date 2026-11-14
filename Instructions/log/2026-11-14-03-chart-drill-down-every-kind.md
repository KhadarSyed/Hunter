# 2026-11-14-03 Chart drill-down: the treemap and the US map never opened their articles; every kind checked in a browser

## Request
A screenshot of the outlet treemap in project 38's deck, with: "drill down is not working in the first project make
sure any chart (Amchart) + other should have drill down and those drill down articles are fetching from the database
right".

## What was wrong (found in a real browser, Playwright, real mouse clicks)
- **Treemap: no tile opened its article list.** `deckcharts.js` `pickable` attached the click to
  `series.rectangles`, but that list stays empty: the tiles are not built from its template, so the handler never
  reached them. The drill data was fine (8 outlets, 8 article lists in the run-5 spec).
- **US map: a state's click did nothing, neither the county zoom nor an article list.** The click listener was added to
  `mapPolygons.template` after the polygons existed. amCharts copies a template's listener only to parts made after it
  is added. Counties had no click at all, although the drill keys are built per state and per county FIPS
  (`analytics.py`).
- **Deck page**: served with no Cache-Control, so a re-rendered deck could be shown stale. Playwright did exactly that.

## What changed
- `deckstudio/vendor/deckcharts.js`:
  - New `clickable(list, fn)`: the template for parts made later, plus each existing part directly; one click runs fn
    once. `pickable` uses it.
  - Treemap: the click goes on `series.nodes` (the tile: rectangle + label), and the treemap's own zoom-on-click is off
    (`toggleKey: "none"`).
  - US map: a state's click zooms to its counties and lists the state's articles; a county's click lists its own (both
    through `clickable`).
- `deliverable/router.py` `_DECK_HEADERS`: `Cache-Control: no-cache`. The browser keeps its copy but checks the ETag on
  every load (304 when unchanged).
- Runs 5 (project 38) and 6 (project 39): `deck.html` re-rendered from the saved spec with the fixed script
  (`deck_store._render_html`, the render a missing deck page already gets). A deck carries its scripts inside the
  file, so decks made before this fix keep the old script until rendered again (Restyle, Fix, or a restore).

## Where the drill-down articles come from
- They come from the database, written into the deck when it is built.
- `deliverable/engine._drill_articles(rows)` takes the approved rows (`rows.load_rows`, from `intel_articles` /
  `intel_article_rq`). `renderer._drill_data` writes them once into `#deck-articles`, and each chart element lists the
  indexes of its own articles.
- The deck page is sandboxed (`connect-src 'none'`), so by design it cannot call the API or the database while open.
- Checked on run 5: the deck's 8 articles are exactly the 8 that analysts approved in project 38. Left out: the article
  marked irrelevant, the keyword-blocked one, the unmatched one and the blocked domain. Each treemap tile lists its own
  outlet's article.

## Verified (browser: a real mouse hover then click at each element's centre; scratch checker kept as
`tests/deckstudio/browser_drill_check.js`, local)
- Run 5 deck, re-rendered: every element with articles opens its list.
  - Treemap 8/8 (it was 0/8).
  - Doughnuts 6/6, bubbles 17/17, stacked bars 5/5, bars 2/2, columns 2/2.
  - Line points: all days with articles. The days with 0 articles have nothing to list, as intended.
- Test deck (scratch) with the kinds these two decks lack: heatmap 4/4, sankey links and nodes 8/8, sunburst 3/3,
  multi-line 4/4.
- US map: clicking Texas zoomed to its counties and listed its 2 articles; Harris County then listed its 1. Table rows
  (`tr.drill-row`) listed their articles.
- The app's route `/api/intel/deliverable/38/runs/5/deck/deck.html` answers 200 with `cache-control: no-cache` and the
  fixed script.
- `pytest -q tests` (minus e2e_3org): 738 passed. ruff and vulture clean.

## Not verified / open
- Clicked by Playwright's mouse in Chromium, not by a person or in another browser.
- A deck rendered before this fix on another server keeps the old script until it is rendered again.
