# 2026-11-12 #25 — strategy moved to SQLAlchemy

## Changed
- `domains/strategy/models.py` (new): intel_search_strategies (10), intel_query_versions (7), intel_datasets (18),
  intel_dataset_files (4, bytea), intel_sample_evaluations (8), intel_question_dimensions (6),
  intel_question_tag_schemas (6), plus intel_article_rq (project_id, rq_id) for RQ deletion.
- `domains/strategy/repository.py`: SQLAlchemy Core, the same 25 public functions (AST-checked), `__all__`.
  RQ add/status/delete keep `FOR UPDATE` (`.with_for_update()`); update_research_question now locks too (it did not:
  an edit racing an add/delete could lose one of them). update_strategy_query's insert + JSON update share one
  transaction. Dataset file copy and restore-after-restart unchanged; the copy no longer returns the bytes.

## Verified
- Parity (scratchpad/strategy_parity.py, old from git HEAD, writes alternated): versions, query versions + applied,
  RQ edit keeps/drops match_query, missing RQ/strategy, RQ add numbering, status, delete (twice) + its Data set rows,
  number never reused, datasets save/parse/error/approve/list/by id/missing, a file deleted from disk restored from
  Postgres, dataset delete removes its file row, evaluations, dimensions and tag schemas upserts: 31 comparisons,
  0 differences.
- pytest strategy, dataset, security: 134 passed; 1 failed = pre-existing test_match_first.
