# 2026-11-14-12 "Sign everyone out" tested live on a temp org; the live socket now opens on every signed-in page

## Request
- "please create another org temp or and temp user and thentest sign everyone out". "GPT comp - stay" (still paused).

## How it was tested without signing the user out
- The button ends every session in the database, and the user's local DB has 24 live sessions.
- So a second backend ran on port 8003 with `HUNTER_PG_SCHEMA_PER_DB=1`: its own throwaway schema
  `t_db4c1f88e0d836fb`, migrated from 0001 at startup. Azure, S3 (`AWS_*`) and mail (`ZEPTO_*`) were blanked for it.
- In that schema: org "TEMP Sign-out Test Org" with its admin, an analyst (two sessions: one open tab, one "other
  device"), and a temp Super Admin. Session tokens went to local files and into the browser cookies, never into a
  tool call.
- Playwright opened one browser context per user. The Super Admin clicked the button and accepted the confirm.

## Run 1: found a bug
- 3 sessions ended, and the Super Admin stayed signed in with the note "3 sessions ended".
- The analyst's tab (/landing) switched to the sign-in page by itself.
- The admin's tab (/org-dashboard) did not: the socket was only opened by pages that use it (`useAgentSocket`,
  `useLiveRefetch`, DataSet, Deliverables), and the org dashboard is not one of them, so it never heard
  `sessions_revoked`.
- Also seen: a signed-out tab kept asking for `/api/auth/ws-ticket` every 30 s forever (each answered 401).

## What changed
- `frontend/src/services/ws.ts`: `disconnect()` closes the socket and stops retries (`stopped` flag).
  `scheduleRetry` and a ticket that arrives late both respect it. `connect()` clears the flag.
- `frontend/src/context/auth-context.tsx`: effect on `user`: signed in → `agentSocket.connect()` (every page,
  every role); signed out → `agentSocket.disconnect()`.

## Run 2 (after the fix, fresh sessions)
- Before the press: all three signed in; the admin on `/org-dashboard`.
- After: the analyst and the admin tabs both showed the sign-in page with no click or reload
  (`.playwright-mcp/signout_admin.png`). The Super Admin was still signed in, and the note said 3 sessions ended.
- In the 8 s after, the signed-out tabs made 0 ws-ticket requests.
- Sessions left in the test schema: only the temp Super Admin's. The main DB: 24 before, 24 after (untouched).
- tsc clean, lint 0 errors (32 warnings), `npm test` 15 passed, build done (served by 8002 from `backend/static`).

## Cleanup
- The 8003 server and the token file server were stopped. Schema `t_db4c1f88e0d836fb` was dropped (gone confirmed),
  and so were the token files. Main backend on 8002: health 200.

## Not verified / open
- The sign-in page photo was dark on 8003 only because S3 was blanked there.
