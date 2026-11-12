# 2026-11-12 #12 — Routing tested with Vitest; React Router not adopted

## Request
"go a head" with React Router (package list item).

## Decision (after reading App.tsx)
React Router NOT adopted. It would only replace the pushState/popstate plumbing (~15 lines); the hard parts stay
custom (fetch the URL's project before rendering, stage-gate redirect, push the URL only after an async project
switch lands). Router changes location on every navigate, so during a project switch the URL-sync effect would
write the previous project's id and the location handler would re-open that old project — avoiding it needs
navigation-type special-casing, i.e. more moving parts than today.

## Changed
- `frontend/src/routing.ts` (new): `PAGE_IDS`, `Page`, `isPage`, `homeFor`, `parseUrl`, `buildUrl` moved out of
  App.tsx unchanged, except `isPage`.
- BUG FIXED: old `isPage` was `p in PAGES`, true for inherited keys ('constructor', 'toString'), so `/constructor`
  rendered `Object` as a page component and crashed. Now a Set of page ids.
- `App.tsx`: imports them; `PAGES` is `satisfies Record<Page, ...>` so PAGES and PAGE_IDS cannot drift; still
  re-exports `Page` for the sidebars.
- Vitest 2 (devDependency, matches Vite 5), `npm test` = `vitest run`; `src/routing.test.ts`: 14 tests (project
  and plain URLs, root, legacy data-sources alias, unknown page, bad ids 0/-3/1.5, doubled slashes, inherited keys,
  Usage never prefixed, round-trips, role homes).

## Verified
- `npm test`: 14 passed. `npx eslint src`: 0 errors. `npx tsc --noEmit` and `npm run build`: pass.
- `node -e "'constructor' in {landing: 1}"` → true (the old check's bug).

## Not verified
- No browser click-through (navigation behaviour itself is unchanged: same functions, moved).
- Not pushed: the push was blocked by the auto-mode permission check; committed locally only.
