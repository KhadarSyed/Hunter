# 2026-11-13-06 Review of the local backup branches; slide-order fix brought back

## Request
"from today we can keep the backup still shows commits not on main review them keep the if required else remove".

## Review (each commit checked against main by patch id, commit message and the code itself)
- `fix/exec-summary-wording`: 0 commits not on main -> deleted.
- `backup/pre-push-with-tests` (8 commits, 2026-09-28, tip `8754218`): all 8 are on main under the same messages
  (re-committed without the local tests, e.g. 7803472, f5a2289, f627dbf, e19ad38, b4730a9, 72c33a1, bb46750) -> deleted.
- `backup/today-2026-11-02` (9 commits, tip `fd43b85`, "backup before revert"):
  - on main under the same message: Boolean research-question queries (2665434), no tagging cap (920f20e),
    500 articles per question (bbe9c26), delete wipes everything (9e0bd0b);
  - superseded on main: time grain + themes-over-time chart (main has `analytics.time_grain` with hour..year and
    `theme_trend`, 2a4932a); in the WIP commit, the country relevance filter (main: `extra_sources._vet` by publisher
    country) and post authors (main: `rows.author_of`);
  - dropped on purpose with the 2026-11-02 revert, never on main: GPU cut-outs (`domains/cutouts`, `workers/cutouts.py`)
    and an Instagram author lookup via Meta's Graph API (no token configured anywhere);
  - still missing and still a bug on main: thumbnails in slide-number order -> brought back (below);
  -> deleted after that.
- Rollback for the deleted backups (commits stay in the reflog ~90 days):
  `git branch backup/pre-push-with-tests 8754218 && git branch backup/today-2026-11-02 fd43b85`.

## What changed
- `backend/domains/deliverable/qc.py`: `by_slide_number()`; `export_pngs` returns slides in slide order.
- `backend/domains/deliverable/router.py` thumbnail route uses it (the n-th thumbnail is slide n, also past 99:
  names are `slide_NN.png`, so by name `slide_100` sorted between `slide_10` and `slide_11`).
- Local test `tests/deliverable/test_slide_order.py`.

## Verified
- `ruff check backend` clean; `pytest -q tests/deliverable` 95 passed + new test 1 passed.
- `git branch -a`: only `main` (local) and `origin/main`.

## Not verified
- A real deck with 100+ slides (none exist locally; no projects created while testing).
