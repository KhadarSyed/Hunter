# 2026-11-14-10 A tab whose session ended goes to the sign-in page; API_KEY vs the SPA flagged

## Request
- "continue". The open item from log 2026-11-14-09: a tab that misses the `sessions_revoked` message (or whose session
  expires) kept failing on every call until a reload, because the frontend had no 401 handling.

## What changed
- `frontend/src/services/intel-api.ts`:
  - New `SESSION_ENDED_EVENT` ("hunter:session-ended"). `json()` and `authJson()` call `noteSessionEnded(res)`.
  - On a 401 it reads a clone of the body and fires the event only for `core/auth.get_current_user`'s two session
    answers ("Not authenticated", "Session expired or invalid").
  - An API-key 401 ("Invalid or missing API key", `core/api.require_api_key`) is not treated as a sign-out.
- `frontend/src/context/auth-context.tsx`: on the event, `setUser(null)`, so the sign-in page shows. It does not call
  `refreshMe`, because `/me` itself answers 401 then, which would loop. The listener is removed on unmount.

## Verified
- tsc clean, lint 0 errors (32 warnings), `npm test` 15 passed, build done. No backend change, so no restart.
- Playwright (temp analyser, session cookie set from a local file, never in a tool call):
  - Signed in on `/landing`. The session was then deleted in the DB.
  - The next in-app navigation (to `/projects`, no reload) showed the sign-in form.
- The temp user and the token files were deleted.

## Found, not changed (needs the user)
- `deploy/render.yaml` sets `ENVIRONMENT=production`, and `core/config.get_app_settings` refuses to start without
  `API_KEY` then. With `API_KEY` set, `require_api_key` (main.py, on every `/api/intel` route) wants an `X-API-Key`
  header, but the SPA never sends one (grep: no `X-API-Key` in `frontend/src`).
- So either Render's real env differs from render.yaml, or the hosted SPA's `/api/intel` calls get 401. Not checked:
  production is down, and Render env is not to be read or changed without the user.

- Follow-up evidence: `require_api_key` and the "API_KEY must be set" check date back to at least d7a425e
  (2026-10-13), and production served the SPA until its database expired (2026-11-11).
  - So Render's real env did not block the SPA: most likely `API_KEY` unset with `ENVIRONMENT` not "production".
    render.yaml's `ENVIRONMENT: production` is then not what runs.
  - Render logs were not read: the Render tool asks which workspace to use, and that is the user's choice.

## Not verified / open
- The "Sign everyone out" button is still not pressed for real (it would end the user's 24 local sessions).
