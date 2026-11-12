# 2026-11-12 #11 — Frontend ESLint; silent failures on Brief & Scope fixed

## Request
"2" (package list): ESLint + Vitest for the frontend.

## Changed
- `frontend/eslint.config.js` (new, ESLint 9 flat config): JS + typescript-eslint recommended + react-hooks.
  `no-explicit-any` and `react-hooks/exhaustive-deps` are warnings (existing debt; adding effect deps blindly can
  cause render loops); `no-unused-vars` ignores `_`-prefixed names. `npm run lint` script; devDependencies eslint 9,
  @eslint/js, typescript-eslint 8, eslint-plugin-react-hooks 5, globals 15.
- `pages/BriefScopeReview.tsx`: four empty catches (save answer, skip question, save edited answer, download spec)
  swallowed failures; now an `actionError` alert (role="alert", same style as DataSet) says what failed, cleared when
  the next action starts.
- `pages/BackgroundResearch.tsx` (2) and `pages/Dashboard.tsx` (4): empty catches on optional pre-fill loads keep
  ignoring failures, now with a comment saying why.
- Removed unused `demo`/`useDemoState` (BackgroundResearch), write-only `articleTotal` state (DataSet), a stale
  eslint-disable comment (auth-context).
- Vitest NOT added yet: no worthwhile test target until the react-router work (parseUrl/buildUrl).

## Verified
- `npx eslint src`: 0 errors, 32 warnings (23 any, 9 exhaustive-deps). `npx tsc --noEmit`: clean.
- `npm run build`: builds (npm 11 warned it skipped esbuild's install script; the build still works).

## Not verified
- Brief & Scope error alert not clicked through in a browser.
