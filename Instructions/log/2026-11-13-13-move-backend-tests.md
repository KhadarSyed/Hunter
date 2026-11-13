# 2026-11-13-13 backend/tests moved into tests/

## Request
"continue" (after log 12: move the 6 passing test files from `backend/tests/` into `tests/` so `pytest tests` runs them).

## What changed (local only: both folders are gitignored)
- `test_azure_payload.py` -> `tests/core/`; `test_empty_charts.py` -> `tests/deckstudio/`;
  `test_latest24h_category.py`, `test_latest_week.py` -> `tests/deliverable/`; `test_price_permission.py` -> `tests/usage/`;
  `test_spec_approve_autorun.py` -> `tests/spec/`. No name clashes; each brings its own fixtures.
- `backend/tests/` removed (empty), so no tests live inside `backend/` any more.

## Verified
- The 6 moved files under `tests/conftest.py`: 38 passed.
- `pytest -q tests` (excluding e2e_3org): 690 passed (652 before + 38).
