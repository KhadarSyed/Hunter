# 2026-11-14-08 "A new version is available" banner after a deploy, without signing out

## Request
- "if any updte code deploy on server - FE should get notification ... can it be done without user log out or has
  to logout for token refresh". Plan approved: "noted, yes".
- Answer: no logout is needed. The session is a server-side row (`sessions`) behind the HttpOnly `session_token`
  cookie, so a deploy or restart does not end it. Only the open tab's JavaScript is old; a reload fixes that.

## What changed
- `frontend/vite.config.ts`: every build gets a `BUILD_ID` made of the time plus the short git SHA ("nogit" when git is
  missing). `define` bakes it into the bundle as `__BUILD_ID__`, and a small plugin writes `version.json`
  (`{"build": ...}`) next to `index.html`. No new env var.
- `frontend/src/vite-env.d.ts`: `declare const __BUILD_ID__: string`.
- `frontend/src/components/NewVersionBanner.tsx` (new):
  - `useNewVersion()` fetches `/version.json` (no-store) and compares it with `__BUILD_ID__`.
  - When it checks: when the live socket reconnects (`agentSocket.onStatus(true)`, since a deploy restarts the
    server), when the tab becomes visible, every 5 minutes, and once on load. It is off on the Vite dev server.
  - The banner says "A new version of AlphaMetricx is available. Reload to use it. You stay signed in." Reload calls
    `location.reload()`; Later hides it until the next reload.
- `frontend/src/App.tsx`: `<NewVersionBanner />` sits beside `<AuthGate />` in `App()`, so it also shows on the
  sign-in page.
- `backend/main.py` `spa_fallback`: `index.html` and `version.json` are now sent with `Cache-Control: no-cache`, so a
  browser revalidates them after a deploy. The hashed `/assets/*` files keep their caching.

## Verified
- tsc clean, lint 0 errors (32 warnings as before), `npm test` 15 passed, build done.
- The build id is in both `backend/static/version.json` and the JS bundle.
- ruff clean; `pytest -q tests` (minus e2e_3org): 740 passed.
- No intel_jobs or deliverable runs were running or queued, so the backend was restarted (Azure blanked).
- `curl` GET: `/version.json`, `/39/matching-label` and `/` answer with `cache-control: no-cache`.
- Playwright on `/`, with a fake deploy (`version.json` rewritten to another id, then the visibility event fired):
  - The banner appears (screenshot `.playwright-mcp/new_version_banner.png`), and Later hides it.
  - After restoring the real file and reloading, no banner shows and the sign-in form is there.

## Not verified / open
- A real Render deploy was not watched. There, the socket reconnect after the restart should trigger the check.
- On a signed-in page, Reload was not exercised. It is a plain page reload, and the session cookie is untouched.
- Unsaved form text in a tab is lost on Reload, as with any reload. That is why the banner offers Later.
