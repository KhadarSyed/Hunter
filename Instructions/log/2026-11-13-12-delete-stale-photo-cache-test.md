# 2026-11-13-12 Stale photo-cache tests deleted

## Request
"yes delete them" (the stale `backend/tests/test_photo_cache.py` noted in log 11).

## What changed
- Deleted `backend/tests/test_photo_cache.py` (+ its `.pyc`): its 4 tests called `deckstudio/assets.cache_key`, which
  no longer exists. Local only: `backend/tests/` is gitignored (`.gitignore` `**/tests/`), so nothing changes in git.

## Verified
- `pytest -q backend/tests`: 38 passed (was 4 failed, 38 passed).

## Follow-up
- The other 6 files in `backend/tests/` (azure payload, empty charts, latest24h category, latest week, price
  permission, spec approve autorun) pass but sit outside `tests/`, so `pytest tests` never runs them.
