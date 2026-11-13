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

- **LLM chain:** `core/llm_provider.py` (`HybridLLMClient`). Only orgs with `organizations.platform_llm` (set by a Super
  Admin: Settings → LLM Providers toggle, `PUT /llm-providers/platform-access`; a new InfoVision starts with it on)
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
  `service.current()` is computed from dates. No payment in the app (gateway + checkout removed 2026-11-13): a Super
  Admin applies every plan with `service.grant` (`POST /billing/orgs/{id}/grant`, "Apply plan" in the org view on
  `/admin`); one applied before expiry is queued to start at the current end, after expiry starts now; the org's admins
  get the activated / renewed email. The Org Admin's Settings → Subscription is read-only. Limits → HTTP 402 on
  user/project create. Sweeper thread every 6 h: queued→active, active→expired, 30/7-day reminders. Emails to Org Admins +
  procurement contact (activated / renewed / reminder / expired).
- **Token allowance:** `user_token_limits` (Org Admin sets per user on `/org-dashboard`). Spend = `llm_usage` this
  month (user's calls + projects they own). Over → `TokenLimitReached` (a `NoChatProviderError`, so stages fall to
  rule-based) + one email per month to the user and Admins. Checked in `HybridLLMClient.chat/chat_tools`.
- **Guardrails:** `domains/guardrails/` (migration 51), Org Admin CRUD in Settings. Added verbatim at the START of
  the system message (provider prompt cache makes repeats cheap) only for stages brief_scope, background_research,
  search_strategy, matching_label, dataset_tagging, deck_engine, deck_studio (`GUARDED_STAGES`). DB read cached 30 s.
  InfoVision's guardrail is seeded once from `guardrails/seed_infovision.md` (user's text, unchanged).

## Reviewer backlog (2026-11-12)

- **Raw SQL → SQLAlchemy** (agreed 2026-11-12, in progress, one domain at a time): `core/sa.py` + `models.py` +
  Core queries per domain. Done: **billing** (log 04), **guardrails, exclusions, assets, memory** (log 05), **datasources, providers** (log 09), **usage** (log 17), **auth** (log 18), **plan, brief** (log 19), **qc** (log 20), **deckstudio, agent** (log 21), **research** (log 22), **deliverable** (log 23), **projects** (log 24), **strategy** (log 25), **spec** (log 26), **dataset** (log 31), direct calls (log 32): DONE. Alembic replaced
  `core/pg.py` and the hand-written schema (logs 37-41: baseline 0001, startup stamping, pg.py deleted).
- **Packages to adopt** (order agreed, log 04): ruff + vulture DONE (log 10); ESLint DONE (log 11); Vitest DONE + react-router DROPPED (log 12). Remaining, adopt WHEN (log 13): openapi-typescript client once
  most routes declare response_model (116/201 today); TanStack Query page by page where a page has a real
  stale-data/refetch problem.
- Dead code removed (log 10): `core/llm_synthesis.py`, 13 unused functions. `domains/agent/qa_browser.py` deleted (log 30, user approved).
- Local `.env` holds ~45 keys no code reads, and python-dotenv cannot parse its line 69 (not opened: may hold a secret).

## Current state (2026-11-13; checked against the local database and code)

- **Production is down; local is the working environment.** Render Postgres `hunter-db` (free plan) expired
  2026-11-11 and is suspended; Render deletes it about 2026-11-25; no upgrade (user's decision, no budget). Work and
  test locally only; never trigger Render/Vercel deploys or change Render env.
- **Local stack:** Docker `hunter-postgres` (port 5433) + backend `uvicorn backend.main:app --port 8002` (serves the
  built SPA). Schema at Alembic revision `0001` (stamped 2026-11-12, log 40). Local Super Admin = the
  `SEED_SUPER_ADMIN_EMAIL` account (user 2); the `.env` seed password no longer matches it (changed at sign-in).
- **Local data:** organisations 1 Default Organization, 2 InfoVision (`platform_llm` on), 3 Test Organization
  (`platform_llm` off); 0 projects. Test Organization's chat models, in failover order: NVIDIA
  `nemotron-3-ultra-550b-a55b` (default), `minimax-m3.1-flash`, `step-5-preview` (logs 34-35). It has a Starter plan
  (+ one queued Starter from a test grant) and an Admin user at the seed address with `+testorg` (logs 2026-11-13-03/04).
- **No GPT spend (finance limit, 2026-11-13):** the local backend runs with `AZURE_OPENAI_API_KEY`,
  `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_MODEL` blanked in the launch command, so nothing can reach the platform
  model; test only on an org's own NVIDIA models. The deck-insight batching A/B (`HUNTER_BATCH_INSIGHTS`) is paused
  until GPT spend is approved; its harness is `tests/e2e_3org/infovision_compare.py casino_ab`.
- **Billing (log 2026-11-13-03):** no payment in the app; a Super Admin applies every plan ("Apply plan" in the org view
  on `/admin`). **Platform model (log 04):** only a Super Admin maps it to an org (LLM Providers switch).
- **NVIDIA models (log 05):** OpenAI-compatible calls are capped at 16384 output tokens; an empty map-step reply is
  asked once more. Tavily answered 432 (plan limit) on 2026-11-13; research continues on its other sources.
- **Storage:** with the `AWS_*` keys set, decks, logos/favicons (linked by signed URL), uploads, avatars and QC files
  live in S3 under `HunterAgent/`; disk copies are throwaway (logs 28, 42, 43).
- **Checks (2026-11-13, end of day):** `pytest tests --ignore=tests/e2e_3org` 643 passed; ruff and vulture clean;
  frontend tsc/lint (0 errors)/Vitest 14/build ok; Apply plan, read-only Subscription tab and the platform-model switch
  checked in the browser (log 04).
- **Deck/brands (2026-11-13, log 2026-11-13-01):** themes-over-time chart (`theme_trend`) added for questions about
  change; Brandfetch guarded (junk names skipped, leading-words match, saved domain reused, paid Brand API cached 30
  days). **All 6 SerpAPI keys reported "exhausted" on 2026-11-13**: Google logo/news/video fallbacks return nothing
  until they reset (user's account).
- **Not verified:** pages that need a project (data set, deck run, strategy content) only in their empty state
  (standing rule: no projects created while testing); a real QC upload/export round trip through S3; `tests/e2e_3org`.
- **Open questions for the user:** when GPT spend is approved, re-enable the `AZURE_OPENAI_*` keys and re-run the A/B.
