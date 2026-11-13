# 2026-11-13-16 How themes, insights and summaries are built (read-only review)

## Request
"I want to know how themes, insights and summaries are generated using dataset after tagging and saved i to db from
vector DB data is passed to LLM for presentation. check this and help me which is besst".

## Findings (from the code, no change made)
- Tagging job (`dataset/tagging_job._run_job`): match -> content -> match full text -> article tags (LLM, batched,
  saved to `intel_articles.tags_json`) -> themes (`_themes_phase`: label counts + 2 headlines each, top 80, one LLM
  call `theme_synthesis.consolidate_labels`, titles saved to `intel_theme_titles`) -> RQ tags (`intel_article_rq`)
  -> relations (`research/relations.find_relations`: embeddings, syndicated >= 0.95, similar >= 0.76/0.86).
- Deck (`deliverable/engine.py` stages): ingest `rows.approved_rows` (Postgres rows, theme titles applied) ->
  compute: per question `theme_synthesis.consolidate` again (question-specific merge, one LLM call), counts and charts
  computed in Python -> insights: `engine_insights.rq_insights` / `section_summaries` -> `insights.draft_section`
  sends FACTS (computed numbers) + up to 12 candidate article excerpts (keyword-ranked by `evidence.rank`, no
  vectors); every number and citation is checked, one repair round, a judge call, rescue, rule-based backfill.
  Results saved per run with `store.save_deliverable_section` (`run.section`).
- Vectors are NOT passed to the LLM. They are used only for syndicated/similar relations, the asset library
  (pgvector) and reference-deck template choice.

## Bug found (not fixed, needs approval)
- `intel_research_item_vectors` has `item_id` as its only key (no FK, no source column). Background Research stores
  vectors under `intel_research_items.id`; the Data set relations phase stores them under `intel_articles.id`. Equal
  ids read/overwrite each other's vector -> wrong syndicated/similar links, and `inherit_article_tags` copies tags
  from a wrongly "syndicated" original. Fix: migration 0004 adding a `kind` column to the key (or a separate table).
- Local DB has 0 articles and 0 research items (815 orphan vectors), so no live collision could be shown here.

## Verified
- Code read only; a read-only SQL count script (scratch) for the numbers above.
