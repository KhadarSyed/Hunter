# 2026-11-12-46 deliverable/cli.py split (logo helpers out); 5 docs about deleted code removed

**Request:** "fix and continue" (the two items still open from the 2026-11-12 audit).

**Changed:**
- New `backend/domains/deliverable/logos.py` (38 lines): `LOGO_TIMEOUT_S`, `LOGO_HEADERS`, `logo_png_url`,
  `is_real_logo`, `save_logo_png`, moved verbatim from `deliverable/cli.py`. `brand_kit.py` and `visuals.py` import
  them from `.logos`, so the app no longer imports from a command-line script; `cli.py` (324 -> 295 lines) imports them
  too and keeps only the reference-deck CLI.
- Deleted `docs/PRESENTATION_COMPOSER.md`, `POWERPOINT_RENDERER.md`, `WORD_RENDERER.md`, `PUBLISHING_GATEWAY.md`,
  `SLIDE_INTELLIGENCE_GUIDE.md` (1030 lines describing code deleted 2026-11-05; grep: no code left). CLAUDE.md's
  pointer removed; `docs/CURRENT_STATUS.md` keeps its dated changelog rows (history).

**Verified:** `ruff` clean; imports of cli/brand_kit/visuals ok; full suite 624 passed; backend restart + browser walk
(see below in the same response).

**Open (user's call):** `deliverable/cli.py` builds one hard-coded "Baby Skincare" reference deck from
`backend/domains/deliverable/projects/baby_skincare.json`, whose input folder `Baby-Skincare_Category/` is not in the
repo, so it cannot run here. Every module it uses is shared with the app: deleting it would remove only cli.py and the
JSON config.
