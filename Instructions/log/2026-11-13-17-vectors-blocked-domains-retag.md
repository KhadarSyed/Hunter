# 2026-11-13-17 Vector key fix, vector add-ons, blocked domains dropped, mark relevant + Re-tag

## Request
"implement the recommendation and fix the bugs. One more thing as per guardrails or block list of domain - system
should better drop it from websearch as well for uploading data to the data set and also make sure presentation
doesn't have the data or citation of those domains. check if this is already happening my reviewer said those
articles are moved to irrelevant". Asked how: "Drop only domain related results not keyword matched, don't tag
irrelevant until user mark it to relevant and has to run retag - during retag only the non tagged relevant articles
should be tagged - already tagged articles should be ignored ... python code ... handles drop domain related, LLM used
only in case where it requires to read the article full content".

## What was already true (checked in code)
- Web research drops excluded domains and keywords before saving (`research/router` `scrub_research`,
  `multi_source` `keep`). The deck drops them (`deliverable/rows._without_excluded`, `latest24h` `keep`); citations
  come only from those rows. Domain matching never used an LLM.
- Tagging only sends `rq_matched != 0` articles with tag_status pending/failed (`articles_needing`), so Irrelevant
  ones are never tagged and tagged ones are never resent; RQ rows are redone only when the RQ schema signature changes.

## Bugs fixed
1. **Vector id collision:** `intel_research_item_vectors` was keyed by `item_id` alone, shared by research items and
   Data set articles. Migration `0004_vector_kind.py` adds `kind` to the key (clears the table: a cache, re-embedded
   on use). `research/models`, `repository.get/save_item_vectors(kind=)`, `relations.ensure_vectors/find_relations
   (kind=)`; `dataset/tagging_job._relations_phase` passes `kind="article"`.
2. **Scheme-less URLs escaped the block list:** `urlparse("blocked.com/a").hostname` is None. `exclusions.service
   .normalize_domain` (now also trailing dot, IDNA, bad URLs) is used for article URLs; new `blocked_domain()`.
3. **Marked-relevant articles were never tagged:** approving an Irrelevant article left `rq_matched = 0`.
   `dataset/repository._analyst_relevant` keeps such articles matched in `save_rq_matches`; `promote_analyst_relevant`
   runs after a non-reject decision (`dataset/router.decide`).

## Changes asked for
- **Blocked websites dropped:** `dataset/service._one` never stores them (result `blocked` count, upload banner says
  "N from blocked websites dropped"); `match_rqs` → `_drop_blocked_domains` deletes articles a later rule blocks
  (`repository.delete_undecided_articles`: an analyst-decided or kept article stays). `blocked_reasons` is keyword-only:
  keyword matches still go to Irrelevant with "Keep relevant".
- **Mark relevant + Re-tag:** Irrelevant view allows selection; `BulkBar relevantOnly` → "Mark relevant for RQx"
  (approves for that RQ); row hover actions hidden there (`ArticlesTable rowActions`).
- **Recommendation 1:** `deliverable/evidence.fuse` / `rerank_by_meaning`: a question's citable articles ordered by
  keyword rank fused (RRF, k=60) with similarity to the question, using the stored article vectors
  (`dataset/repository.article_vectors`); the set never changes. Wired in `engine.py` after `evidence_by_rq`.
- **Recommendation 2:** `theme_synthesis.tail_map`: labels beyond the top 80 join the theme of their nearest top label
  when cosine >= 0.85 (`TAIL_MERGE_MIN`, shortcut comment: unmeasured), else keep their wording. Callers now pass all
  labels (`consolidate`, `tagging_job._themes_phase`).

## Verified
- New tests: `tests/core/test_migrations.py::test_0004...`, `tests/dataset/test_blocked_domains.py` (13),
  `tests/deliverable/test_vector_ranking.py` (6). Full `pytest -q tests` (minus e2e_3org): 710 passed.
- `ruff check backend` clean; vulture clean; frontend `tsc` clean, lint 0 errors, `npm test` 15 passed; build done.
- No running/queued jobs; backend restarted (Azure blanked): HTTP 200, local DB at 0004, vectors table empty.

## Not verified
- Before/after deck quality of the two vector add-ons on a real project (needs a project + chat LLM; not created).
- The 0.85 tail threshold and the passage-type question embedding on real NVIDIA vectors.
- The new Irrelevant-view bulk bar in a browser.
