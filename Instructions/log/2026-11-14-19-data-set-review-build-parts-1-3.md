# 2026-11-14-19 Data set review: build parts 1-3 (matching, scope filter + pools, source data)

## Request
- "stop the backend and implement". The design was agreed over the session; the sample artifact is
  https://claude.ai/artifact/KGTKt2NCTuxtHeTMC9D38H (private).
  - Table: select, article (logo, linked title, outlet/domain, date, author; social: platform logo, account, post),
    country, access, main brand, competitors, sentiment, relevancy %, syndicated / similar counts (click = list),
    status, Approve / Reject.
  - Above the table: KPIs; Relevant · Irrelevant · Out of scope · Blocked switch; Approve all / Reject all.
  - Scope filter: country + date range from a two-month calendar dropdown, defaulting to the uploaded data's range.
  - Per-RQ tabs. Editable drill-down with full article text, rich tags and comments (article / question scope) that
    feed the agent's memory. One "Map" action (upload → guardrails → scope → match → tag) with a live pipeline.
- The backend was stopped first. That ended project 41's running re-tag (RQ4); it resumes from its checkpoint at the
  next start.

## Done (each pushed on main)
1. `2f00708` matching evaluates the Boolean query.
   - New `dataset/boolean.py`: AND / OR / NOT (unary and binary), NEAR/n read as AND, implicit AND, title:/headline:.
     It reuses `question_dimensions.keyword_hits`.
   - `service._matching` uses it; an unreadable query falls back to any positive term and is logged.
   - Deleted `not_terms`, `_own_level`, `_without_disambiguations` (log 17's patch).
   - Project 41 dry run (614 articles): RQ1 601, RQ2 460, RQ3 8, RQ4 192, RQ5 18, RQ6 131, RQ7 517, RQ8 81, RQ9 135.
     The old loose match gave RQ3 258, RQ5 237, RQ8 589. About 2,143 article×RQ rows instead of 3,582.
   - RQ2's query ANDs the brand with "casino", which is in the brand name "Foxwoods Resort Casino", so it matches
     most articles. That is the query's wording (editable in the RQ panel), not the matcher.
2. `80edd7e` scope filter and pools.
   - `service.scope()`: the saved `spec["data_set_scope"]`, else the uploaded data's own min/max date and the single
     Brief & Scope country. A saved "" (every country) wins over the default.
   - `scope_reasons()`: "Out of scope: ..." for an article outside the date range or with another country. An article
     with no date or no country is kept for that part; one an analyst kept is never set aside.
   - `set_scope()` saves and re-matches. `match_rqs` treats out-of-scope like blocked (`save_blocked`), and a block
     wins over scope.
   - `repository`: `OUT_OF_SCOPE_PREFIX`; the pool filter gains `blocked` / `outscope`, and `irrelevant` now means
     "matched no question" only. `tagging_counts` gains `blocked` and `out_of_scope`. `match_texts` returns published
     and country. No migration.
   - Router: `GET` / `PUT /articles/{pid}/scope` (`ScopeRequest {country, from, to}`, 422 when from > to); the list
     `pool` accepts blocked / outscope.
3. `ebc8743` source data.
   - JSON upload (`_json_rows`: a list, `{"articles": [...]}` or the first list in the object; nested values kept as
     JSON text). `ALLOWED_EXT` adds `.json`, and the frontend input accepts it.
   - Site memory: `article_extractor._site_refuses()`. When a site's last 3 cached fetches
     (`research_article_fulltext`, new `research.repository.recent_site_statuses`) were all paywalled, or all blocked
     (401 / 403 / 429), the next article is not scraped and gets the same status with "site skipped". The skip is not
     cached, so a site that starts working again is re-checked.
   - Author: `article_extractor.extract_author(html)` (meta author, schema.org author, byline) with `is_person_name`,
     both moved from `qc/service.py` (which now calls them).
     - `_extract` returns `author`; `content.fetch` returns (text, status, author).
     - `repo.save_content(..., author)` fills `author_name` only where the export left it empty.

## Verified
- ruff clean.
- Local tests: `tests/dataset` 117 passed after part 2; `tests/dataset` + `tests/qc` + `tests/research` 234 passed,
  then `test_content` 13 passed after the host fix.
- New tests (local): Boolean AND/OR/NOT, NEAR, wildcards, implicit AND, title:, fallback (`test_query_panel.py`);
  `test_scope_filter.py` (defaults, saved range, several countries, JSON rows); `test_content.py` (byline, site
  memory).

## Not done yet (next)
- Outlet country: the export's Country column, else the country domain (.co.uk), else the tagger naming the outlet's
  home country. Today `country` is empty for project 41.
- Per-RQ records API; editing the rich tags and RQ tags; comments with kinds `comment` / `rq_comment` in
  `intel_tag_feedback` (shown back to the taggers).
- The "Map" endpoint (upload → scope → match → tag) and the step-named live progress.
- Frontend: rebuild `DataSet.tsx` / `ArticleDrawer.tsx` to the sample.
- The new tagger stays off until the 60-article side-by-side.
- Project 41 has not been re-matched with parts 1-2 yet (the backend is stopped). The next start resumes its re-tag
  first.
