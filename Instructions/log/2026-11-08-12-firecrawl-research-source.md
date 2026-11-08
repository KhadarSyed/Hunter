# 2026-11-08 #12 — Firecrawl research source (org key) + encrypted data-source keys (part B of the image/guard/firecrawl plan)

**Request (spec 2):** Firecrawl as an extra research web search, only with the org's own key from Settings, in
parallel with existing sources, same item table, de-dup keeping the richer record, cost guardrails, tests.
User added `FIRECRWAL_API_KEY` (note spelling) to .env — used only for live checks; research uses the org key.

**Analysis:** sources fan out in `research/news_search.fetch_and_normalize` (SerpAPI, Tavily, Google News RSS +
`extra_sources`: YouTube, Bluesky, SearXNG); items → `intel_research_items` (`source_api` = provider). Org keys:
`domains/datasources/`, table `org_data_sources` — keys were stored in PLAIN TEXT (now fixed).

**Built:**
- Migration 53: org_data_sources CHECKs allow `firecrawl` and statuses `unverified`/`quota`; `settings_json`;
  `organizations.allow_editorial_images` (for part A).
- `datasources/repository.py`: Fernet-encrypted keys (`core/secret_box`), legacy plain rows readable and converted at
  startup (`encrypt_legacy_keys`, main.py lifespan; 1 Tavily key converted locally), `get_source`, `update_settings`,
  `delete_key`. `schemas.py`: Firecrawl meta + `FIRECRAWL_DEFAULTS` {enabled, max_results 5, full_content}, mask = last 4.
  `service.check_firecrawl`: ok / expired (401/403) / quota (402/429) / unverified (network/5xx).
- Routes: PUT (Firecrawl checked first: 401 refused, unreachable saved `unverified`), PATCH `/settings`, DELETE,
  existing POST `/validate` = Test connection. Admin only.
- `research/extra_sources.search_firecrawl`: POST /v2/search (sources web+news, tbs from date range, country,
  scrapeOptions markdown onlyMainContent when full_content), timeouts 15 s / 30 s, 5xx retried ×2, 24 h cache per
  query+filters, `FIRECRAWL_SEARCH_ENABLED` kill switch, logs count/latency/creditsUsed (never the key).
- `news_search`: `firecrawl` in EXTRA_SOURCES, runs only with `api_keys["firecrawl"]` options; cross-source de-dup now
  keeps the richer content and records `_providers` (logged; `source_api` stays the first source).
  `multi_source.GENERAL_EXTRA_SOURCES` += firecrawl. `research/router._firecrawl_options(org)`: key + options when
  saved, enabled, not rejected; out-of-credits marks `quota`.
- UI `DataSourcesTab.tsx`: Firecrawl card (use-in-research toggle, results per search, full page toggle), Test
  connection, Remove key, statuses Invalid key / Not verified yet / Out of credits.

**Verified:** tests/research 99 passed (15 new in `test_firecrawl.py`, all HTTP mocked). Live (Acme test org, removed
after): analyst 403; bad key 422; real key saved masked ••••b5a5, stored encrypted, test ok; real search 4 items with
full content; toggle off → skipped; removed.

**Still to do (same plan):** A deck images licence-safe by default (+Openverse/Pixabay, credits, editorial switch),
C Guardrails check stage in Deliverables, D two-user cross-project browser test + research compliance check.
