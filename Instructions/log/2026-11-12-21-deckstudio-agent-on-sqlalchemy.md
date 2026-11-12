# 2026-11-12 #21 — deckstudio (reference deck library) and agent moved to SQLAlchemy

## Changed
- `domains/deckstudio/models.py` (deck_reference_decks 6 columns, unique path; deck_reference_slides 5) +
  `repository.py` (6 functions, `__all__`). Upsert/delete of a deck and its slides each run in one transaction.
- `domains/agent/models.py` (agent_memory 6, unique project+kind+key; agent_events 7; agent_autopilots 6;
  agent_issues 12 — `note`/`seen` keep their server defaults) + `repository.py` (9 functions, `__all__`;
  OPEN_ISSUE_STATES stays internal: nothing outside reads it). No raw SQL on these tables elsewhere (grep).

## Verified
- Parity (scratchpad/deck_agent_parity.py, old from git HEAD, writes alternated): deck upsert new/existing, slide
  replace incl. empty list, slides by type and order, delete cascade + unknown path; memory upsert/list/kind
  filter/delete, events with limit and after_id paging, autopilot attempts carried over and explicit, list by
  status, issue de-dupe by fingerprint (seen+1), closed issue not reused, server defaults: 30 comparisons,
  0 differences.
- pytest agent, deckstudio, memory: 68 passed; 1 failed = pre-existing test_live_slides (label format).
