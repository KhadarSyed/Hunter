# 2026-11-12-30 qa_browser deleted, pre-existing failing tests fixed

**Request:** "please continue your journey" (remaining list; user approved earlier: delete brief copies +
`qa_browser.py`, fix the pre-existing failing tests).

**Deleted:** `backend/domains/agent/qa_browser.py` (standalone argparse CLI, imported by nothing; grep of code,
tests, scripts). The 19 `data/uploads/brief_*` copies were already gone with the log-27 wipe.

**Tests (local only, `tests/` is gitignored), each judged code-right vs test-stale before editing:**
- `core/test_object_store.py::test_disabled_without_env`: conftest's autouse fixture replaces `_client` with a stub,
  so `cache_clear()` failed. Test keeps a reference to the real `_client` taken at import.
- `deliverable/test_latest24h.py` (6): commit 9b0ef0b moved the live feed from 24 h to 7 days on purpose. Tests now
  use the 7-day edge (167.9 h in, 168.1 h out; offset case 26 Oct), the daily peak bullet and 8 daily points.
- `deckstudio/test_live_slides.py`: same change, daily timeline labels pass through unchanged.
- `deliverable/test_time_grain.py` (4 removed): they test `_theme_trend` from commit 48a1f73, which is NOT an
  ancestor of main (an unmerged branch), so the code never existed here. Worth asking whether that themes-over-time
  chart was meant to ship.
- `dataset/test_match_first.py`: content phase deliberately also fetches short unmatched rows (second match on the
  body, no LLM; commit 572eb64). Test now asserts that, and that the LLM tag phase gets only matched originals.
- `amcharts/test_sunburst.py` (failed on HEAD too): fake rows were SimpleNamespaces missing new fields; now real
  `EngineRow` + `Article`.

**Verified:** `pytest tests --ignore=tests/e2e_3org` -> 623 passed + sunburst 2 passed (0 failed).
**Not run:** `tests/e2e_3org` (needs a live three-org setup).
