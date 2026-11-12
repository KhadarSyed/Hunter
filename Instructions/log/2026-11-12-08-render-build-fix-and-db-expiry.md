# 2026-11-12 #08 — Render build fix; production database suspended (free plan expired)

## Request
"superb please proceed / run a read-only query on the production database" (llm_usage by stage, for the LLM-call
review in log #06).

## Found (read-only, Render API)
- Production Postgres `hunter-db` (dpg-db6i680m7kps73e06280-a, free plan) **expired 2026-11-11 18:12 UTC and is
  suspended (billing)**. Render: 14-day grace to upgrade to a paid plan, then the database and all data are deleted
  (https://render.com/docs/free) → deadline ≈ 2026-11-25. Upgrading is the user's billing decision; not touched.
- Its IP allowlist is empty, so no external query is possible: the llm_usage query was NOT run.
- Every deploy of web service `hunter-intelligence-platform` today failed: 07:08 and 07:17 `update_failed`
  (built, could not start: database suspended); from 07:33 (`39d57b0`) on `build_failed`.
- Build failure cause (build log): `requirements.txt` changed in 39d57b0, so Docker reinstalled packages without
  cache and got the new `playwright` 1.65.1, whose Node driver needs `libatomic.so.1`, missing in python:3.12-slim;
  `playwright install --with-deps chromium` exited 127.

## Changed
- `deploy/Dockerfile`: `apt-get install libatomic1` before the pip/playwright step.

## Verified
- Clean `python:3.12-slim` container + playwright 1.65.1: without libatomic1 → same error as Render; with it →
  `Version 1.65.1`.
- Full local `docker build -f deploy/Dockerfile .` → success; inside the image `backend.main`, billing/memory
  repositories, SQLAlchemy 2.1.8, cryptography, bcrypt 4.3.0 import; `playwright --version` works.

## Not verified
- The Render deploy itself: it will build, but the app cannot start until the database is upgraded/restored.
