# 2026-11-12-47 Hard-coded reference-deck CLI removed, with the code only it used

**Request:** "continue no hard coded remove it" (the Baby Skincare reference-deck CLI, log 46).

**Deleted:** `backend/domains/deliverable/cli.py` (295 lines) and `deliverable/projects/baby_skincare.json` (its
hard-coded project; the input folder it named was never in the repo). Then, repeatedly, every top-level function,
class or constant in `deliverable/metrics.py`, `classify.py`, `deck.py`, `ingest.py` whose name occurs exactly once in
all of `backend/` + `tests/` (its own definition; names inside strings count, so dynamic lookups are kept): 31 names,
467 lines -- entry points `compute_metrics`, `compute_classified_metrics`, `classify_theme`, `build_deck`,
`load_articles`, then the helpers/constants only they used (`_theme_metrics`, `_trend_slide`, `_set_cover`,
`expert_label`, `_EXPERT_LABELS`, `ClassificationUnavailable`, `TEXT_COLUMNS`, `DEFAULT_COLUMNS`, ...).
`deliverable/logos.py` docstring updated (no CLI user any more).

**Verified:** `ruff` clean (unused imports removed by --fix); vulture only the known `handle_decl` false positive;
`import backend.main` ok; full suite 624 passed; backend restart + browser walk (same response).
