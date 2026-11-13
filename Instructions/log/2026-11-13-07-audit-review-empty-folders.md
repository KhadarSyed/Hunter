# 2026-11-13-07 Ponytail audit + review of today's commits; empty folders removed

## Request
"/ponytail-audit /ponytail-review and verify all the changes required all the hard coded are now resolved and unused
code are removed, also remove empty folders".

## Checks run (results)
- `ruff check backend`: all checks passed. `vulture backend --min-confidence 80 --exclude backend/static`: nothing.
- `npx tsc --noEmit`: clean. `npm run lint`: 0 errors, 32 warnings (`any` / effect deps, allowed).
- Unimported frontend `.ts/.tsx` files (grep of every basename in imports): none.
- Hard-coding grep (drive paths, /Users, /home, user name, company email, localhost/IPs) in backend + frontend/src:
  none, except named constants: `config.DEV_ORIGINS` / `app_url` default (local Vite), public API base URLs, and the
  two default LibreOffice install paths in `core/nvidia_parse_client._find_soffice` (after `shutil.which`).
- `.env.example` vs code: every listed var is read (LOG_LEVEL/ZEPTO_*/MAIL_FROM_NAME through pydantic settings).
  Mismatch found: see finding 2 below.

## Empty folders removed (untracked / gitignored, nothing in git changed)
`agent/` (old `agent/data/briefs`, `agent/data/rendered`), `database/seaweedfs-s3.json/` (Docker created it for the
gone `hunter-objects` container), empty `data/{backups,deliverables,exports,qa,recreate_inputs,specifications,verbatims}`,
`data/uploads/avatars`, empty `.ruff_cache/0.16.9` folders, `docs/video-guide/.hyperframes/*-lock`. The code recreates
every runtime folder it uses (`mkdir(parents=True, exist_ok=True)`). Kept `.claude/worktrees` (Claude Code's own).

## Findings reported, NOT fixed (waiting for the user's pick)
1. `core/org_chat_clients._stream` sends `max_tokens=16384` to every OpenAI-compatible model; a model or vLLM server
   with a smaller output/context limit answers 400 on every call (the only 400 retry drops stream_options, not max_tokens).
2. `research/pexels.py` reads only `PEXEL_API_KEY`; `.env.example` lists `PEXELS_API_KEY` (deckstudio/assets.py reads
   both), so a key set as documented never reaches the research brief / project background images.
3. `deploy/start-all.ps1` / `stop-all.ps1` still handle the `hunter-objects` container (no container, no compose file).
4. `research/brandfetch.py:108`: a joined line with a 13-space gap (cosmetic).
5. `billing/repository.create_subscription`: `starts_at`/`ends_at` optional + `payment_ref` name, one caller left.

## Not verified
- Finding 1 against a real small-limit model (reasoned from the code path only).
