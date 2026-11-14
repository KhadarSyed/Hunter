# 2026-11-14-09 Test projects 38/39 removed (project delete now cleans S3); Super Admin "Sign everyone out"

## Request
- "image behind sign-in not required / 2 Test project - remove / 4 fine / 3 - stay paused".
- So: no login card image; delete test projects 38 and 39; build the optional "sign everyone out" button (item 4);
  the GPT batching A/B stays paused.

## What changed
- `backend/domains/projects/repository.py` `delete_project` (used by `DELETE /api/intel/projects/{id}`): bug fix.
  - Before, it removed rows and local files but left the project's S3 objects (uploaded data set files, stored
    decks) and its decks' rows in the shared asset library.
  - New `_s3_keys()` reads `s3_key` from every table that has both `project_id` and `s3_key`
    (`intel_upload_files`, `intel_deliverable_files`). Those objects are deleted after the commit, counted as
    `s3_objects`.
  - The project's `deck` / `run-<id>` rows in `intel_asset_library` are deleted in the same transaction.
  - The shared library has no `project_id`, so its other assets are never read or deleted.
- Super Admin "Sign everyone out":
  - `auth/repository.delete_other_sessions(keep_token)`.
  - `POST /api/auth/sessions/sign-out-everyone` (Super Admin only, 403 otherwise) ends every session but the
    caller's. It broadcasts `{"type": "sessions_revoked"}`.
  - `core/events.audience_for`: new allowlist `_EVERYONE = {"sessions_revoked"}` (no data in it) goes to every
    socket. Other untagged messages still reach Super Admins only.
  - Frontend:
    - `auth-context` listens for `sessions_revoked` and re-checks `/me`, so an ended session drops to the sign-in page.
    - `intelApi.signOutEveryone()`.
    - Settings → Manage Organization has a "Sign everyone out" panel with a confirm dialog and a result note.
- Data removed (local DB + shared S3 bucket):
  - Projects 38 and 39 (scratchpad `checks/cleanup.py`): 1110 + 1675 rows, 2 analyst corrections, 21 vectors,
    781 cached test answers, exclusion rules 36/37, the test session, 3 S3 upload objects, and their deck S3 files.
  - 26 orphaned S3 objects under `decks/project-38/run-2-cc82c7db/` (Foxwoods run 2, uploaded 2026-11-13, i.e.
    local: Render's database was already suspended then). No row pointed at them. They use an older nested key
    layout; today's `deck_store.persist` deletes old keys, so an earlier code version probably left them (not
    confirmed).

## Verified
- New tests:
  - `tests/projects/test_delete_files.py::test_delete_project_removes_its_s3_objects_and_deck_library_rows`
    (Postgres): only the project's two keys are deleted, the other project's are kept, and only its library row goes.
  - `tests/security/test_access_and_hardening.py`: four new tests. `sessions_revoked` reaches an analyser, an
    untagged message does not, and the route works for a Super Admin (keeps "mine", broadcasts). Admin and analyser
    get 403. `delete_other_sessions` against Postgres ends 3 of 4 and keeps the caller's.
- ruff clean; `pytest -q tests` (minus e2e_3org): 746 passed.
- Frontend: tsc clean, lint 0 errors (32 warnings), `npm test` 15 passed, build done.
- After the cleanup:
  - 0 projects and no rows with project_id 38/39 in any table, 0 deck library rows.
  - S3 `decks/` and `datasets/` prefixes for both projects are empty.
- Live, after the backend restart (no jobs or runs): the temp analyser's POST got 403.
  - A temp Super Admin (session cookie set in the browser from a local file, never in a tool call) saw the panel
    (`.playwright-mcp/sign_everyone_out.png`).
  - Cancel on the confirm left all 26 live sessions untouched.
  - Both temp users, their sessions and the token files were deleted; no orphan rows remain.

## Not verified / open
- The button was not pressed for real: the local DB has 24 live sessions (yours included), all of which it would end.
  The tab-to-sign-in-page reaction to `sessions_revoked` is untested in a browser.
- An open tab whose socket is disconnected at that moment does not hear the message; its next API call fails until
  a reload (there is no global 401 handler).
