# HunterAgent — Instructions (read this first)

Start here before reviewing any code. This folder is the working memory for the project: the map below says where
things live, the rules say how work is done, and `log/` holds one note per response with the full detail of what
changed and why. Open the code only for the files a note or the map points to.

## How to use this folder

1. Read this README (map + rules + current state).
2. Read the newest notes in `log/` (newest first) for recent changes in the area you are touching.
3. Only then open the specific files named there.
4. After every response, add a note to `log/` (`YYYY-MM-DD-NN-topic.md`) and update "Current state" below if it changed.

## Standing rules

- Commit on `main`, push, restart the backend after every fix. No pending branches.
- Before a restart, check for running/queued jobs (`intel_jobs` status running/queued); a restart kills them.
- `tests/` and `docs/superpowers/plans/` stay local (gitignored); never push them.
- No manual Render/Vercel deploys and no Render env changes; pushing `main` auto-deploys.
- Never print, log or commit API keys, `.env` values or session tokens. Provider keys live only Fernet-encrypted in the DB.
- Do not create projects when testing ("test e2e except create project").
- Quality over speed; work inline rather than through subagents.
- Test emails go to khadar.syed@infovision.com only.

## Run and check

| What | Command |
|---|---|
| Backend | `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8002` (repo root) |
| Frontend dev | `npm run dev` in `frontend/` → http://localhost:5173 (proxies `/api`, `/ws` to 8002) |
| Type check | `cd frontend && npx tsc --noEmit` |
| Tests | `python -m pytest -q tests/<area>` (local only) |
| Clear bytecode | delete `backend/**/__pycache__` before a restart |

## Map: page → frontend → backend

| Stage / page | URL | Frontend | Backend |
|---|---|---|---|
| Projects | `/projects` | `pages/ProjectsPage.tsx`, `LandingPage.tsx` | `domains/projects/` |
| Brief & Scope review | `/{id}/brief-scope-review` | `pages/BriefScopeReview.tsx` | `domains/spec/`, `agents/brief_scope.py` |
| Background Research | `/{id}/background-research` | `pages/BackgroundResearch.tsx` | `domains/research/` |
| Search Strategy | `/{id}/search-strategy` | `pages/SearchStrategy.tsx` | `domains/strategy/router.py` |
| Matching label | `/{id}/matching-label` | `pages/MatchingLabel.tsx` | RQ routes in `domains/strategy/router.py` |
| Data set | `/{id}/data-set` | `pages/DataSet.tsx`, `components/dataset/` | `domains/dataset/` (tagging_job, router) |
| Deliverables | `/{id}/deliverables` | `pages/DeliverablesPage.tsx` | `domains/deliverable/`, `domains/deckstudio/` |
| Settings (tabs via `?tab=`) | `/settings?tab=providers` | `pages/SettingsPage.tsx` | `domains/auth/`, `domains/providers/` |
| Usage & cost | `/usage` | `pages/UsagePage.tsx` | `domains/usage/` |

- Routing is hand-rolled in `frontend/src/App.tsx` (`PAGES`, `parseUrl`, `buildUrl`); stage gating redirects a locked
  stage to the open one (`gateRedirect`, `domains/projects/gates.py`).
- Stage pages use a sticky bottom action bar (← Back / Proceed →); Matching label also has a sticky top bar.

## Key subsystems

- **LLM chain:** `core/llm_provider.py` (`HybridLLMClient`). Only orgs with `organizations.platform_llm` (InfoVision)
  use platform GPT-5; every other org uses its own providers (Settings → LLM Providers).
- **Failover:** `domains/providers/service.call` tries the org's models in order (saved default, then newest first),
  marks a down model for 120 s, waits and rechecks every 5 min when all are down (12 h cap), never falls back to the
  platform. `classify()`: 5xx/429/network = outage, 401/403/404/access = config, 400/cut-off/bad JSON = not failover.
- **Outage state + emails:** `domains/providers/outage.py`, table `org_llm_state` (migration 49). One email per
  event (switched / paused / recovered) to the org's Admins (`email_layout.org_admins`).
- **Emails:** one layout for all — `core/email_layout.py` + `core/templates/email.html.j2`. Project emails in
  `domains/deliverable/notify.py`, account emails in `domains/auth/recovery.py`, outage emails in `providers/outage.py`.
  Button links use `APP_URL`, else Render's `RENDER_EXTERNAL_URL`, else `http://localhost:5173` (`core/config.py`).
- **Auth:** forgot password = 6-digit code → reset link; 12-character policy (`domains/auth/service.py`).

## Current state (2026-11-08)

- Orgs: InfoVision (org 5; admins Sweta Shah, Harish), Testing Org (org 6; VyceAI agnes default, NVIDIA Nemotron,
  Azure GPT-5). Only Khadar is a seeded Super Admin.
- Project 1 "Casino Gaming" (InfoVision): Brief → Matching label done, Data set open, Deliverables locked.
- Testing Org outage state: acting model NVIDIA (VyceAI in maintenance); a real "recovered" email goes out when
  VyceAI answers.
- Known pre-existing test failures: `tests/deliverable/test_latest24h.py`, `test_time_grain.py`
  (`analytics._theme_trend` no longer exists).
- Known limits: first call after an outage can take ~3 min (client retries before failover); Background Research
  and Search Strategy can finish rule-based during a long outage.
