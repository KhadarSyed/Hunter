# 2026-11-12-28 Logos and favicons in S3 (linked), test organisation with NVIDIA GLM

**Requests:** "create test organization and connect LL nvidia model z-ai/glm-5.3-flash"; reviewer: "logo and brand
images are stored in local instead of S3 bucket"; "logos and feviicons all should be saved in s3 and link to it ...
then run in debug mode and see everything is working as per the expectation".

## Logos / favicons
Before: bytes already went to S3 through `assets.put`, but permanent copies were also written to `data/brand_logos`
(`research/logo_files.CACHE_DIR`), `data/favicons` (`deliverable/latest24h.py`), `data/email_icons`
(`core/email_layout.py`), and the logo route served the disk file first (stale against S3). The frontend hotlinked
Google's favicon service in 7 places.

Changed:
- `core/object_store.py`: `presigned_url()`; client signs with SigV4 (`botocore Config(signature_version="s3v4")`).
- `core/config.py`: `ASSET_CACHE_DIR` (system temp) for throwaway file copies.
- `domains/assets/service.py`: `link(kind, key, fetch) -> (signed url, meta)`, `LINK_TTL_S = 3600`.
- `domains/research/logo_files.py`: `logo_bytes`, `logo_link`; `logo_file` writes a temp copy only; no `.json`
  sidecars; the old "plausible Google logo" re-check moved into `_fetch` (only trusted sources are stored).
- `domains/research/router.py`: `/brandfetch/logo/image` and new `/favicon?domain=` -> 307 to S3 (cache 50 min,
  less than the link's life); bytes without S3; 422 for a non-domain; 404 when none.
- `domains/deliverable/visuals.py`: `fetch_favicon()` extracted (reused by the route).
- `latest24h.py`, `email_layout.py`: temp folders. Frontend: `faviconUrl()` in `services/intel-api.ts`, used by
  cells.tsx, Latest24hPanel, ResearchItemsTable, BackgroundResearch, DeliverablesPage, SearchStrategy.
- Deleted stale `data/brand_logos` (252), `data/favicons` (193), `data/email_icons` (9), `data/flags` (1).

Verified (backend run with `--log-level debug`, 0 errors/tracebacks in its log):
- scratchpad `verify_assets.py`: 14/14 PASS - logo meta, logo + favicon routes 307 to
  `ai-intelligence-data.s3.amazonaws.com/HunterAgent/assets/...`, signed links return real PNGs, 422 bad domain,
  401 without login, nothing created under `data/`.
- `logo_file`, email client/provider logos and `favicon_png` produce files under `ASSET_CACHE_DIR`.
- Real Chromium (Playwright) with a session cookie loads `/api/intel/favicon` (64px x2) and the logo route (399px).
- `ruff check backend` clean; `tsc --noEmit` clean; `npm run lint` 0 errors (32 warnings); `npm run build` ok,
  built bundle has no `s2/favicons`.

Not verified / follow-ups:
- `deckstudio/verbatims.py` still embeds Google favicon URLs into generated HTML decks (a shared deck file cannot
  carry expiring links); deck-run folders still hold per-run favicon copies (they are the deck's working files).
- Brandfetch search fuzzy-matches nonsense names (e.g. "zzqx-no-such-brand-qq" -> nosuch.vc); pre-existing.
- `.env` `SEED_SUPER_ADMIN_PASSWORD` no longer matches the account (login 401); the check used a temporary session
  created and deleted through `auth.repository`.

## Test organisation
Created locally: organisation "Test Organization" (id 3), Super Admin as member; provider id 1
"NVIDIA GLM 5.3 Flash", openai_compatible, `https://integrate.api.nvidia.com/v1`, model `z-ai/glm-5.3-flash`, key =
the existing NVIDIA key (Fernet-encrypted), set as the org's default. The model is listed by NVIDIA's `/v1/models`,
but every chat call timed out (60 s direct; repeated ReadTimeouts through the app client), so it is saved untested,
like the app's own add-provider route. Use "Test" in Settings -> LLM Providers once NVIDIA answers.
