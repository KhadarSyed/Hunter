# Deck images — licensing / legal note (read before touching image fetching)

Written 2026-11-08 at the user's request ("must not face any legal issue — make a note of it"). This is an
engineering risk note, not legal advice; get InfoVision legal sign-off before client decks use web images.

## Where deck photos come from today (`backend/domains/deckstudio/assets.py`)
Order per slide (`_plan` / `find_photo` / `_fallback`):
1. Brand-owned image the project already has (brand imagery) — trademark/brand use, OK for reports about the brand.
2. **Cited articles' lead image** (`article_image`: og:image / twitter:image of the slide's own source articles).
3. **Web image search**: SearXNG → DuckDuckGo → SerpAPI Google Images (`licence="web"`).
4. Licensed stock: Pexels, Unsplash (`licence="licensed"`). Brand-led slides try web first, others stock first.
5. Wider fallback: SerpAPI / SearXNG at category level, also pulling each result page's og:image.
Reuse: `domains/assets` (S3 + Postgres `intel_asset_library`, embedding similarity) — a photo is reused across
orgs before any search. Wikimedia photos are checked (`deckstudio/commons.py`): non-commercial licences are skipped,
attribution-required ones get a credit page.

## Risk ranking
| Source | Licence status | Risk in a paid client deck |
|---|---|---|
| Pexels | Pexels licence: free commercial use, no attribution required (credit appreciated) | Low |
| Unsplash | Unsplash licence: free commercial use; API guidelines require attribution + download ping (done) | Low |
| Wikimedia Commons (commercial-OK licences) | CC0 / PD / CC-BY / CC-BY-SA with credit | Low (credit page exists) |
| Brand's own logo / press imagery | Trademark nominative use | Low–medium |
| **Article og:image (cited sources)** | Copyright of the publisher / photo agency (often Getty/AP/Reuters) | **High** |
| **SerpAPI / SearXNG / DuckDuckGo / Tavily images** | Unknown — any copyrighted image on the web | **High** |

"Publicly available" ≠ licensed. A search engine returning an image grants no right to reuse it; news photos are
frequently agency-licensed and actively enforced (copyright-claim letters per image).

## Gaps found
- Pexels / Unsplash photographers are NOT credited in the deck (only Wikimedia credits are written).
- Web / article images carry no credit and no licence record.
- No switch to keep client decks licence-safe.

## Rule going forward (proposed, awaiting approval)
- Default for client decks: **licence-safe sources only** (reuse of licence-safe library rows → brand assets →
  Wikimedia/Openverse commercial-OK → Pexels → Unsplash → Pixabay), every photo credited.
- Article / web-search images only when an org explicitly enables "editorial use", always with a visible
  "Image: <source domain>" credit and listed for analyst review; never for brands/people the article doesn't cover.
- Never strip watermarks, never use images from domains whose robots.txt / X-Robots-Tag disallow image use.
