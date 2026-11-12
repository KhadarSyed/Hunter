# 2026-11-12 #13 — Generated API client and TanStack Query: not now (criteria recorded)

## Request
"ok": continue the package list; also pushed the local routing commit (54febc2) — the earlier push had been blocked
by the auto-mode permission check, the retry went through.

## Measured
- Backend routes: 201; with `response_model=`: 116 (58%). A client generated from FastAPI's OpenAPI would type the
  other 85 as unknown, so the hand-written frontend types (~1,700 lines in services/intel-api.ts + types/) stay.
- Frontend: 159 `useEffect` fetch patterns; no stale-data / double-fetch bug found in the audit or logs.

## Decision
- openapi-typescript: adopt once most routes declare `response_model` (add them domain by domain first).
- TanStack Query: adopt page by page where a page has a real caching/refetch problem, not as a blanket rewrite.

## Changed
- `Instructions/README.md` backlog only.
