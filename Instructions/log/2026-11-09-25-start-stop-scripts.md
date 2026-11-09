# 2026-11-09 #25 — Start-all / stop-all PowerShell scripts

User: "start servers", then "give two script to start all servers and stop all servers manually note : not bat file
should be a script".

**Why start failed today:** Rancher Desktop's Docker engine hung ("timed out dialing Hyper-V socket"), which stopped
`hunter-postgres` (5433); after the restart Postgres ran crash recovery before accepting connections. Separately a
`.venv-gpu` is first on PATH and lacks the backend packages (`cryptography`), so plain `python` cannot run uvicorn.

**Added:**
- `deploy/start-all.ps1`: Docker up (`rdctl start` if Docker does not answer) → `docker start hunter-postgres`, wait
  for `pg_isready` → `hunter-objects` if it starts (warns otherwise) → backend on 8002 with the first Python that can
  import uvicorn/fastapi/psycopg/cryptography → Vite on 5173. Skips anything already listening. Logs in `data/logs/`.
- `deploy/stop-all.ps1 [-Force]`: refuses while `intel_jobs` has running/queued rows (unless -Force), kills the
  5173 and 8002 process trees, stops hunter-postgres / hunter-objects. Leaves Rancher Desktop running.
- `deploy/start.ps1` (old, port 8000) left as is.

**Checked:** start with all up (skips), stop, cold start: all OK, backend picked system Python 3.12.

**Open:** `hunter-objects` (SeaweedFS S3, port 9000) cannot start: its mount `database/seaweedfs-s3.json` is missing.
The app falls back to Postgres for stored files.
