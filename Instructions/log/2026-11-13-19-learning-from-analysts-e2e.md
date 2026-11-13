# 2026-11-13-19 Learning from analyst corrections; synthetic project end to end on NVIDIA; fixes it found

## Request
"I did not build learning from analyst corrections - this should be happening. recreate the synthetic 10 articles
project until deck creation and see in test org using nvidia test and fix". Scope chosen: organization-wide (the
question was not answered; same scope as the exclusion overrides).

## Learning from analysts (built, commit b60828f)
- Migration `0005_tag_feedback.py`: `intel_tag_feedback` (org_id, source_project_id, article_id, rq_id, question, kind,
  before/after JSON, comment, article_text, pgvector embedding, model). `source_project_id` on purpose: deleting a
  project keeps the organization's learning.
- `domains/feedback/` (models, repository with `__all__` re-exported by `core/store.py`, service): `record()` saves in
  the background (job runner, embeddings in batches of 50, max 200 per request); `guidance()` embeds a tagging batch,
  takes the org's nearest corrections (cosine >= `MIN_SIMILAR` 0.62, 2 per article, 6 per call) as a prompt section.
- Recorded from `dataset/router`: tag edit (`learn_edit`, only when something changed; new optional `comment` on
  `ArticleEdit`), reject with reason and "mark relevant" of an Irrelevant article (`learn_decision`; approving an
  already-matched article is not recorded), "Keep relevant" (`learn_keep`).
- Used by `agents/article_tagging.tag(..., hints=)` (edits) and `agents/rq_tagging.tag(..., hints=)` (reject /
  relevant / keep), wired in `dataset/tagging_job`.
- Frontend: "Why?" field in the tag edit drawer and in the Irrelevant "Mark relevant" bar.

## End to end (synthetic project 38, Test Organization, NVIDIA Nemotron 3 Ultra, no GPT)
- Upload 9 added + 1 blocked website dropped; tagging 342 s.
- Corrections through the API: solar article sentiment Positive -> Neutral with comment, rejected for RQ1 with reason.
- First Re-tag of a similar new article (EV chargers): no hint -> similarity was 0.696 vs the 0.80 start value.
  Measured article pairs: same kind of story 0.68-0.70, different stories 0.39-0.53 -> `MIN_SIMILAR` = 0.62.
- Same model, same prompt, with vs without the corrections: EV article Positive / RQ1 relevant -> Neutral /
  "Corporate sustainability initiatives" / RQ1 not relevant; the slot-machines control got no hint, unchanged.
- Deck run 2 (old code): completed, 33 slides, 17/17 checks after one repair round; deck scan: blocked domain,
  blocked keyword, both Irrelevant articles and the rejected solar article are on no slide.

## Fixes the run found
1. `core/org_chat_clients.OpenAICompatClient.chat`: a reply cut off at the output cap, or an empty JSON reply (the
   reasoning model spent its budget thinking: 4 insight cards fell back to rule-based in run 2), is retried once with
   `reasoning_effort: "low"` (probed: integrate.api.nvidia.com accepts "low"/"none"); a refused retry keeps today's
   outcome. Tests: `tests/providers/test_reasoning_retry.py`.
2. `domains/providers/service`: "Received multimodal data but multimodal processing is not enabled" (photo checks sent
   to a text-only model) was an "outage": the model was marked down 7 times and "switched"/"recovered" emails went to
   the org admin. New class "capability": the next model is tried, no down mark, no email; none able ->
   `OrgProviderError` (the caller's fallback). Test: `test_a_model_that_cannot_take_images_is_skipped_without_an_outage`.
3. Test fakes for the new `hints` keyword (`test_tagging_job`, `test_query_panel`); table count 119 in
   `test_migrations`.

## Verified
- `pytest -q tests` (minus e2e_3org): 722 passed; ruff clean; vulture clean; frontend tsc clean, lint 0 errors,
  `npm test` 15 passed, build done. Local DB at 0005.

## Not verified / open
- Deck run 3 with fixes 1-2 is running (before/after numbers go in the next note).
- `MIN_SIMILAR` 0.62 rests on 10 article pairs; re-measure on a real project's corrections.
- The synthetic project 38 is kept until the user has looked at it in the browser; then cleanup (cleanup.py also
  deletes its `intel_tag_feedback` rows).
- A 10-article deck took ~2.5 h on Nemotron 3 Ultra (insight drafting and photo checks dominate).
