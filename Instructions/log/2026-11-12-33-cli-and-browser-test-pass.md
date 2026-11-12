# 2026-11-12-33 CLI + browser test pass; two hard-coded project ids and the Settings tab gate fixed

**Request:** "do the testing and help me all the fixes are done both cli and browser level".

**CLI (all green):** `ruff check backend` clean; vulture: only the known false positive
(`deckstudio/creative.py:96`, an `HTMLParser.handle_decl` override parameter); `pytest tests --ignore=tests/e2e_3org`
-> 624 passed; frontend `tsc --noEmit` clean, `npm run lint` 0 errors (32 warnings), Vitest 14/14, `npm run build` ok.
Earlier in the session (logs 28-32): live S3 logo/favicon check 14/14, CORS preflight/CSRF checks, parity checks.

**Browser (headless Chromium, scratchpad `browser_walk.py`):** Super Admin via a temporary session (deleted after),
Test Organization active; every top-level page, all 8 Settings tabs, and project pages opened with no project.
Records console errors, page errors, API >= 400, failed requests, broken images; screenshots in scratchpad/shots.
First pass: 18 pages, 2 with issues. After the fixes: 21 pages, 0 problems; the LLM Providers tab shows
Test Organization with NVIDIA GLM 5.3 Flash (default, not tested).

**Fixed (found by the walk):**
- `DeliverablesPage.tsx` and `ResearchPlan.tsx` used `useActiveProjectId() ?? 1`: with no project open they loaded
  project 1's data (another org's project on a real database; a Super Admin passes the access check). Now a thin
  wrapper shows `components/NoProjectSelected.tsx` and the unchanged body (`DeliverablesView`, `ResearchPlanView`)
  gets a real project id. No other `?? <number>` project fallback in `frontend/src` (grep).
- `SettingsPage.tsx`: `?tab=` opened any tab, even one the role does not have (Super Admin + `subscription` -> the
  billing API's 400 "org_id is required"). Now an unavailable tab falls back to My Profile.

**Not verified / open:**
- NVIDIA `z-ai/glm-5.3-flash`: listed by NVIDIA, but every chat call times out (280 s via the app's Test
  connection, 45 s direct). The key works (NVIDIA answers other calls at once with 404/410 for retired models), so the
  model endpoint itself is not serving. The provider stays saved as "Not tested".
- Pages that need a project (data set, deck run, strategy content) were checked only in their no-project state:
  the standing rule is not to create projects while testing.
- `tests/e2e_3org` not run (needs a live three-org setup).
