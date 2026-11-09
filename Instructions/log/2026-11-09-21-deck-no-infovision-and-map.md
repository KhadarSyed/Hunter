# 2026-11-09 #21 — No InfoVision on decks; why the Casino deck has no map

User: "remove Infovision and its logo from the presentation" / "Why Regional deck din't produce the MAP?"

**InfoVision removed from decks**
- The only place InfoVision reached a deck was the badge top-right on every slide (`deckstudio/renderer._house_badge`:
  InfoVision gif + "InfoVision Intelligence" + AlphaMetricx). The badge now shows AlphaMetricx's wordmark only.
  `HOUSE_LOGO` removed from `core/config.py`; `.house-name/.house-word/.house-sep/.house img` CSS removed.
- Applies to decks built from now on. Decks 1 (Casino) and 2 (Planet Fitness) were built before and still carry it.
- Hidden metadata: the house PPT template's revision history (`ppt/changesInfos/`) names an infovision.com author.
  Not visible on slides; not changed (ask if it must be stripped on export).
- Tests: deckstudio 57 passed (test_live_slides pre-existing failure deselected).

**Why the Casino ("regional") deck has no map**
- The map module (`catalog.with_us_map`, `analytics._us_map`) is added only when enough of a question's articles carry
  a US location (`us_locations.map_reason`), on the first question that asks "where/region/state/local".
- The Casino datasets have 12 columns (Date, URL, Keywords, Information Type, Source Name, Author Name, Author Handle,
  Title, Opening Text, Hit Sentence, Hashtags, Reach) — no Country/State/Region/City. 0 of 1000 articles have a
  location (run log: "567 unique articles (567 with no country kept)"), so no map can be drawn.
- RQ2/RQ5 ("national vs regional outlets (CT, MA, RI, NY)") were answered as an outlet-scope split (doughnut), not a map.
- Planet Fitness's export has country/region/state/city on every article → its deck got the `us_map` module.
- Possible fix (not built): infer a state from the outlet (e.g. Hartford Courant → CT) or ask for a Meltwater export
  with location columns.
