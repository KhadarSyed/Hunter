# 2026-11-13-01 Themes-over-time deck chart; Brandfetch credit guard

**Request:** "I WANT THEMES OVER TIME DECK CHART / BRAND fetch yes it should guard for to avoid un necessary credits
usage", then "yes continue" (designs approved).

**Themes over time:** `deliverable/analytics.py` `_theme_trend` (ported from unmerged commit 48a1f73 onto today's
time-grain helpers): one 100% bar per period (grain from the data's span, finest = day), top 5 themes, latest 12
periods with themed articles, a fact per period, click-through per period and per period+theme. Registered in
`_HANDLERS`; `catalog.py` MODULES entry + `_ensure_required` adds it to a question about change (`_CHANGE_ASK`:
develop/evolve/over time/trend/change/shift/spike/grow/decline/emerge/year-on-year) when its articles carry dates and
themes, one over MAX_MODULES so stored plans lose nothing; `engine.py` passes reused stored plans through
`_ensure_required`; `deckstudio/checklist.py` (trend asks), `deckstudio/pipeline.py` UNMARKED_CHARTS,
`deliverable/visuals.py` icon. Drawn as stacked bars by the existing breakdown path (chart_choice GROUPS, amcharts).

**Brandfetch guard:** `research/brandfetch.py`: `worth_looking_up()` (no Brandfetch/Google call for empty, numeric,
1-character or generic-only names) in `resolve_logo`, `resolve_brand_domain`, `candidate_domains`,
`google_logo_candidates`; `_is_plausible_match` now needs the match to be the query or its leading words (not a piece
inside a word, not a later word); `resolve_brand_domain` reuses the domain the logo lookup saved in `brand_logos`
and skips the search after a fresh "not found". `deliverable/brand_kit._brand_api` (the paid Brand API) answers from
the asset store (`brand_data`, 30 days; 404 remembered a week); `assets/service.py` knows `brand_data`, stores it as
.json and never embeds it (no embedding call).

**Verified:** tests (local) RED -> GREEN: `tests/deliverable/test_time_grain.py` 11 passed (5 new),
`tests/research/test_brandfetch_guard.py` 6 passed; full suite 635 passed (run 2026-11-12 before the machine
restarted; code unchanged since); ruff clean. Local cache re-checked against the new rule: 6 ok, 1 wrong
(`zzqx-no-such-brand-qq` -> nosuch.vc, my own test) deleted from `brand_logos` + its logo asset row; it now resolves to
no logo.

**Found, not fixed:** all 6 SerpAPI keys report "exhausted" (2026-11-13): Google logo/news/video fallbacks return
nothing until they reset. **Not verified:** a real deck with a change question (needs a project); the Brand API cache
against the live paid API (would spend a credit).

**Also:** the machine restarted; `hunter-postgres` was restarted (`docker start`) and the backend started again.
