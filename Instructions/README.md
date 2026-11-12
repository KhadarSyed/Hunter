# HunterAgent — Instructions (read this first)

Start here before reviewing any code. This folder is the working memory for the project: the map below says where
things live, the rules say how work is done, and `log/` holds one note per response with the full detail of what
changed and why. Open the code only for the files a note or the map points to.

## How to use this folder (every request, every session — also stated at the top of `CLAUDE.md`)

**Before** the work:
1. Read this README (map + rules + current state).
2. Read the newest 3-5 notes in `log/` (newest first) for recent changes in the area you are touching.
3. Only then open the specific files named there, and confirm in the code every fact you will rely on.

**After** the work, in the same response:
4. Add `log/YYYY-MM-DD-NN-topic.md` (next NN for that day) with: the request, what changed (files, functions,
   commits), how it was verified (command + result), what was NOT verified, and follow-ups.
5. Update "Current state" / the map below if they changed, and commit the note with that response's work.

## No-hallucination rules

- Facts come from the code, not from memory or docs: grep/read before naming a file, function, env var, table,
  endpoint or default. This README, `CLAUDE.md` and old log notes go stale; when they disagree with code, fix the doc.
- `.env.example` lists exactly the variables the code reads: add new ones in the same change, remove dropped ones.
- No hard-coded machine paths, user names, emails or hosts in code; use `core/config.py` constants or env vars.
- Say "not verified" for anything not run. Never claim tests pass without their output.
- Remove dead code rather than keeping it "for later"; grep every caller (code and local `tests/`) first.

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
| Start all / stop all | `powershell -ExecutionPolicy Bypass -File deploy/start-all.ps1` / `deploy/stop-all.ps1 [-Force]` (Docker, hunter-postgres, backend 8002, Vite 5173) |
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
| Platform dashboard (Super Admin home) | `/admin` | `pages/AdminDashboard.tsx`, `components/admin/` | `domains/billing/` |
| Org dashboard (Org Admin home) | `/org-dashboard` | `pages/OrgDashboard.tsx` | `domains/billing/` |
| Settings → Subscription / Guardrails | `/settings?tab=subscription` | `SubscriptionTab.tsx`, `GuardrailsTab.tsx` | `domains/billing/`, `domains/guardrails/` |

- Routing is hand-rolled in `frontend/src/App.tsx` (`PAGES`, `parseUrl`, `buildUrl`); stage gating redirects a locked
  stage to the open one (`gateRedirect`, `domains/projects/gates.py`).
- Stage pages use a sticky bottom action bar (← Back / Proceed →); Matching label also has a sticky top bar.

## Key subsystems

- **LLM chain:** `core/llm_provider.py` (`HybridLLMClient`). Only orgs with `organizations.platform_llm` (InfoVision)
  use platform Azure GPT (gpt-5 or gpt-4.x, set by `AZURE_OPENAI_MODEL`; GPT-5-only params are dropped for gpt-4); every other org uses its own providers (Settings → LLM Providers).
- **Failover:** `domains/providers/service.call` tries the org's models in order (saved default, then newest first),
  marks a down model for 120 s, waits and rechecks every 5 min when all are down (12 h cap), never falls back to the
  platform. `classify()`: 5xx/429/network = outage, 401/403/404/access = config, 400/cut-off/bad JSON = not failover.
- **Outage state + emails:** `domains/providers/outage.py`, table `org_llm_state` (migration 49). One email per
  event (switched / paused / recovered) to the org's Admins (`email_layout.org_admins`).
- **Emails:** one layout for all — `core/email_layout.py` + `core/templates/email.html.j2`. Project emails in
  `domains/deliverable/notify.py`, account emails in `domains/auth/recovery.py`, outage emails in `providers/outage.py`.
  Button links use `APP_URL`, else Render's `RENDER_EXTERNAL_URL`, else `http://localhost:5173` (`core/config.py`).
- **Auth:** forgot password = 6-digit code → reset link; 12-character policy (`domains/auth/service.py`).
- **Roles / homes:** `App.tsx homeFor()` — Super Admin → `/admin`, Org Admin → `/org-dashboard`, Analyser → landing.
  A Super Admin can NOT open projects (`core/auth.can_access_project` returns False); they review them on `/admin`.
  Only a Super Admin creates orgs (form: name, logo data-URI ≤1 MB, procurement name/email/phone, address, country,
  PIN, first plan); the procurement email becomes the org's Admin.
- **Subscriptions:** `domains/billing/` (migration 50). Plans limit users + projects only (orgs buy their own models).
  `service.current()` is computed from dates; renewal paid before expiry is queued to start at the current end, after
  expiry starts now. Test gateway only (`TestGateway`; swap behind `PaymentGateway`). Limits → HTTP 402 on user/project
  create. Sweeper thread every 6 h: queued→active, active→expired, 30/7-day reminders. Emails to Org Admins +
  procurement contact (activated / renewed / reminder / expired).
- **Token allowance:** `user_token_limits` (Org Admin sets per user on `/org-dashboard`). Spend = `llm_usage` this
  month (user's calls + projects they own). Over → `TokenLimitReached` (a `NoChatProviderError`, so stages fall to
  rule-based) + one email per month to the user and Admins. Checked in `HybridLLMClient.chat/chat_tools`.
- **Guardrails:** `domains/guardrails/` (migration 51), Org Admin CRUD in Settings. Added verbatim at the START of
  the system message (provider prompt cache makes repeats cheap) only for stages brief_scope, background_research,
  search_strategy, matching_label, dataset_tagging, deck_engine, deck_studio (`GUARDED_STAGES`). DB read cached 30 s.
  InfoVision's guardrail is seeded once from `guardrails/seed_infovision.md` (user's text, unchanged).

## Reviewer backlog (2026-11-12)

- **Raw SQL instead of an ORM** (open, needs a decision): ~384 `execute()` calls over 31 files, SQLite-style SQL
  translated to Postgres by `core/pg.py`, schema + migrations hand-written in `core/db.py` (~1,900 lines).
  Moving to SQLAlchemy models + Alembic means rewriting every repository; not started. See log 2026-11-12-01.
- `domains/agent/qa_browser.py`: standalone CLI (argparse), imported by nothing; keep or delete is the user's call.
- Local `.env` holds ~45 keys no code reads, and python-dotenv cannot parse its line 69 (not opened: may hold a secret).

## Current state (2026-11-08)

- Orgs: InfoVision (org 5; admins Sweta Shah, Harish), Testing Org (org 6; VyceAI agnes default, NVIDIA Nemotron,
  Azure GPT-5). Super Admin (global) = Harish Thulasiram. Since 2026-11-12 the seed is env-driven
  (`SEED_SUPER_ADMIN_EMAIL`) and runs only while NO Super Admin exists, so it never re-promotes anyone. Khadar is an
  Admin of InfoVision (org 5) alongside Sweta Shah (local DB; prod keeps Khadar as Super Admin until changed there).
  Production checkout is closed while only the test gateway exists; a Super Admin grants/renews plans with
  `POST /api/intel/billing/orgs/{org_id}/grant {plan_id}` (no UI button yet). Both orgs: Enterprise plan to 2027-11-08 (backfill).
  InfoVision has the "Instructions/Guardrail Prompt" guardrail (11,003 chars). Sweta Shah still has the
  first-login password-change flag (all her API calls 403 until she changes it).
- Test orgs from the 3-org browser test (log #06): 9 Acme Retail, 10 Globex Media, 11 Initech Finance (all "Test
  11081934"), accounts `khadar.syed+<org>-admin/-analystN@infovision.com`; harness `tests/e2e_3org/run.py`.
- Working test model: BazaarLink `qwen3.7-flash` only; FreeModel 503, CodeCraft/RadoxAI 402, Puter unusable.
- Deck images are licence-safe by default (`deckstudio/assets.py`, legal note `Instructions/image-licensing-legal-note.md`);
  org opt-in for editorial images in Settings > Guardrails; `IMAGE_SOURCE=legacy` = old behaviour.
- Firecrawl research source needs the org's key in Settings > Data Sources (none saved yet); all data-source keys are
  Fernet-encrypted (migration 53). Deliverables shows a Guardrails check above the downloads.
- Data set: exclusion list blocks articles at Match (Irrelevant, "Blocked"); "Mark relevant" + comment → org memory.
- Project 1 "Casino Gaming" (InfoVision): Brief → Matching label done, Data set open, Deliverables locked.
- Testing Org outage state: acting model NVIDIA (VyceAI in maintenance); a real "recovered" email goes out when
  VyceAI answers.
- Known pre-existing test failures: `tests/deliverable/test_latest24h.py`, `test_time_grain.py`
  (`analytics._theme_trend` no longer exists).
- Known limits: first call after an outage can take ~3 min (client retries before failover); Background Research
  and Search Strategy can finish rule-based during a long outage.
