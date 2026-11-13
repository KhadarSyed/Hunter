# 2026-11-13-18 Checked the vector changes and the Mark relevant bar on a synthetic project, then cleaned up

## Request
"implement the recommendations - hope user comment, change(edit) of any tagged item are saved in RAG and indexed ..."
then "Check these" (the 0.85 cutoff and before/after of the vector changes; the Mark relevant bar in a browser).
Asked: learning from analyst corrections -> user answered "avoid this" (not built). Test project -> "put test data with
10 articles ... then delete the synthetic articles and related projects keep clean". A/B batching stays paused.

## Checks (synthetic project 4 in Test Organization, 10 articles, NVIDIA models only, no GPT)
- **0.85 cutoff** (NVIDIA embed, 24 label pairs): near-synonyms 0.68-0.89, different issues 0.48-0.76 ("Store openings"
  vs "Store closures" 0.763). 0.85 merges 3/12 synonyms, 0 wrong; below ~0.77 opposites merge. Kept 0.85; numbers in
  the comment above `theme_synthesis.TAIL_MERGE_MIN`.
- **Upload + tagging (265 s):** 9 added, 1 blocked-website row dropped; keyword-blocked and off-topic articles in
  Irrelevant, untagged; 7 tagged; 9 vectors stored as kind "article"; themes consolidated into 5 titles.
- **Citation order before/after** (real rows, real embeddings): same set both ways; RQ2 unchanged, RQ1 reordered. With 7
  articles the insight step offers all of them anyway (cap 12), so a deck difference needs a larger data set.
- **Browser (Playwright, Test Org admin session):** Irrelevant view shows the 2 articles, new help text, no row buttons;
  bar lists RQ1/RQ2, "Mark relevant for RQ1" saved (toast). Re-tag from the page: only the marked article (5027) was
  tagged; the 7 tagged articles' tags and RQ rows were unchanged (md5 before/after); the decision stayed "approved".

## Fixes found by the checks (commit 22b77c8)
- `frontend/src/pages/DataSet.tsx`: pool counts did not refresh after a decision/undo -> `syncTagging()` after both.
- `backend/domains/dataset/router.undo`: an undone "mark relevant" left the article Matched -> re-runs the free match.
  Test: `tests/dataset/test_router.py::test_mark_irrelevant_relevant_then_undo_returns_it_to_irrelevant`.
- `tests/memory/test_memory.py` wrote into the dev database on every run (4 memory rows each since 2026-11-12) -> runs
  in its own throwaway schema now (verified: dev `memory_items` count unchanged by a run).

## Cleanup (verified)
- Deleted project 4 (82 rows), its 9 vectors, the 2 test exclusion rules, the test session, the S3 upload copy; 112 leaked
  test memory rows (`org-<hex>` entities/relationships, `agent_<hex>:` lessons) and 67 cached test answers; scratch token
  file and the day's `.playwright-mcp` snapshots. After: 0 projects, 0 vectors, 0 org-3 exclusions.
- The test session token was echoed once in the Playwright tool output; the session was deleted, so it is void.

## Verified
- `pytest -q tests` (minus e2e_3org): 711 passed; ruff clean; frontend tsc clean, lint 0 errors, build done.

## Not verified
- A full deck run on the synthetic project (not needed for these checks; long on NVIDIA models).
