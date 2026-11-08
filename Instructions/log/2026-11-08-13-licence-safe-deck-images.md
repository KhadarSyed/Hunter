# 2026-11-08 #13 — Deck images licence-safe by default (part A)

**Request:** Deck images must not create legal issues; prefer cited-article images for relevance then SerpAPI,
Tavily, Pexels, Unsplash, SearXNG, DDG; discover other free/credit sources. User chose **Licensed by default** (article
and web images only when an org opts in). Legal note: `Instructions/image-licensing-legal-note.md`.

**Built (`deckstudio/assets.py`, signatures unchanged):**
- Policy: `legacy_mode()` (`IMAGE_SOURCE=legacy` → exact old behaviour, rollback), `editorial_allowed()` (org flag
  `organizations.allow_editorial_images`, read via the deck run's usage scope → project → org; default off).
- New licence-safe adapters: `_openverse` (no key; `license_type=commercial`; CC/PD with creator + licence),
  `_pixabay` (`PIXABAY_API_KEY`, Pixabay Content License); Pexels/Unsplash now return credits (photographer, licence,
  page). Editorial-only adapter `_tavily_images` (include_images). Adapters return None on error, [] when no key.
- `licensed_sources()` order `IMAGE_LICENSED_PROVIDERS=openverse,pexels,unsplash,pixabay`. `_guarded()`: 24 h
  (provider, query) cache + circuit breaker (3 failures → 10 min skip).
- `_plan`: licensed only by default; with opt-in: cited articles first, then licensed, then serpapi, tavily, searxng,
  duckduckgo. `_fallback`: licensed stock at category level by default (no page og:image).
- Library reuse: an earlier run's `web`/`article` photo is not reused in a licence-safe deck.
- `_credit_for`: every kept photo credited (stock credit / Wikimedia licence / editorial "Image: <domain>",
  "Editorial use — © the rights holder"); `planner.photo_credits_slides` uses the credit's title.
- Settings → Guardrails: "Deck images" switch (Admin; confirm dialog states the copyright risk); API
  `GET/PUT /api/intel/guardrails/policy`.

**Verified:** tests/deckstudio 57 + new `test_image_licensing.py` 11 (licensed default never calls article/web,
opt-in tries articles first, credits, no web reuse, breaker + cache, adapters, missing key, legacy flag);
`test_photo_fallback.py` pinned to legacy order. Suites 165 passed; `test_live_slides` fails before and after
(pre-existing). Live: Openverse 20 results (CC BY 2.0…), Pexels + Unsplash credits present.

**Not done:** disk-free rendering (images still saved in the deck folder: cropping + slide Fix depend on it);
perceptual de-dup already existed (`dhash`). `PIXABAY_API_KEY` not in .env yet (Pixabay skipped until added).
