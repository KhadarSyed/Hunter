# 2026-11-12 #07 — VS Code debug config

## Request
".vscode put": add the user's `settings.json` and `launch.json` under `.vscode/`.

## Changed
- `.vscode/settings.json`: Python envs default manager = venv.
- `.vscode/launch.json`: "Hunter backend (debug)" runs `uvicorn backend.main:app` on 127.0.0.1:8002 under debugpy,
  cwd = repo root, PYTHONPATH = repo root (same as the Quick Start command, no --reload).

## Notes
- Pick the interpreter that has the backend's packages (Python312), not `.venv-gpu` (lacks them; see CLAUDE.md).
- Needs `.env` with DATABASE_URL and local Postgres up, like any backend start.

## Not verified
- The debug launch itself was not started from VS Code.
