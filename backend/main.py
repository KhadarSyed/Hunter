"""Application factory.

`create_app()` wires the Intelligence Platform (`domains` routers under /api/intel)
plus the shared /ws event socket, the HTTP layer (request ids, timing, error envelope),
and the built React SPA from backend/static/ (so one server on :8002 serves everything).

Run: python -m uvicorn backend.main:app --host 0.0.0.0 --port 8002
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # before importing modules that read os.environ at import time

from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from sqlalchemy import literal, select  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .core import events, jobs, object_store, sa, store  # noqa: E402
from .core.api import install_http_layer, require_api_key  # noqa: E402
from .core.auth import seed_super_admin_if_missing  # noqa: E402
from .core.config import (  # noqa: E402
    BACKEND_DIR,
    UPLOAD_DIR,
    get_app_settings,
)
from .domains import router as intel_router  # noqa: E402
from .domains.auth.router import router as auth_router  # noqa: E402

logger = logging.getLogger("hunter")

STATIC_DIR = BACKEND_DIR / "static"
GZIP_MIN_BYTES = 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_intelligence_db()
    seed_super_admin_if_missing()
    store.cancel_stale_running_jobs()
    store.fail_interrupted_deliverable_runs()
    store.fail_interrupted_latest24h_refreshes()
    from .domains.memory import service as memory
    memory.purge_expired()
    from .domains.guardrails import service as guardrails
    guardrails.seed()
    from .domains.datasources import repository as datasources
    if n := datasources.encrypt_legacy_keys():
        logger.info("encrypted %d data source key(s) stored before encryption", n)
    from .domains.billing import service as billing
    billing.start_sweeper()
    events.bind_loop(asyncio.get_running_loop())
    from .domains.agent import autopilot
    autopilot.resume_all()
    try:
        from .domains.deliverable import templates_index
        templates_index.warm_in_background()
    except Exception as e:
        logger.warning("reference deck warm-up not started (%s)", type(e).__name__)
    try:
        from .domains.usage import prices
        prices.sync_in_background()
    except Exception as e:
        logger.warning("price sync not started (%s)", type(e).__name__)
    logger.info("Hunter started (%s)", get_app_settings().environment)
    try:
        yield
    finally:
        events.bind_loop(None)
        jobs.runner.shutdown(wait=False)
        logger.info("Hunter stopped")


_AVATAR_NAME = re.compile(r"^avatar_\d+_[0-9a-f]{8}\.(png|jpg|gif|webp)$")


def mount_uploads(app: FastAPI, upload_dir: Path) -> None:
    """Publicly serve only avatars (briefs, QC exports and other uploads under UPLOAD_DIR are never web-accessible):
    this server's copy, else the S3 copy (a hosted server's disk does not survive a restart)."""
    @app.get("/uploads/avatars/{filename:path}", include_in_schema=False)   # the whole rest: odd paths get a 404
    def avatar(filename: str):
        if not _AVATAR_NAME.match(filename):
            raise HTTPException(404, "Not found")
        path = upload_dir / "avatars" / filename
        if path.is_file():
            return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})
        link = object_store.presigned_url(f"avatars/{filename}")
        if link:
            return RedirectResponse(link, status_code=307, headers={"Cache-Control": "private, max-age=3000"})
        raise HTTPException(404, "Not found")


def _mount_spa(app: FastAPI) -> None:
    if not STATIC_DIR.is_dir():
        return
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str):
        if full_path.startswith(("api/", "ws")):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        file = (STATIC_DIR / full_path).resolve()
        if file.is_file() and STATIC_DIR.resolve() in file.parents:  # no path traversal
            return FileResponse(str(file))
        return FileResponse(str(STATIC_DIR / "index.html"))


# Stage of an LLM call made while serving a request; first match wins. Matching label's RQ routes live under
# /strategy, and the strategy router's /dataset and /evaluation uploads are the Search Strategy dataset check.
_STAGE_BY_PATH = [("/research-question", "matching_label"), ("/final-approve", "matching_label"),
                  ("/api/intel/brief", "brief_scope"), ("/api/intel/spec", "brief_scope"),
                  ("/api/intel/research", "background_research"), ("/api/intel/strategy", "search_strategy"),
                  ("/api/intel/dataset", "search_strategy"), ("/api/intel/evaluation", "search_strategy"),
                  ("/api/intel/articles", "dataset_tagging"), ("/api/intel/deliverable", "deck_engine"),
                  ("/api/intel/agent", "agent"), ("/api/intel/qc", "qc")]


def _stage_for(path: str) -> str:
    return next((stage for frag, stage in _STAGE_BY_PATH if frag in path), "other")


async def usage_scope(request: Request, call_next):
    """One usage-scope holder per request; the auth dependencies fill org, user and project into it."""
    from .domains.usage import service as usage
    token = usage.SCOPE.set({"stage": _stage_for(request.url.path)})
    try:
        return await call_next(request)
    finally:
        usage.SCOPE.reset(token)


def create_app() -> FastAPI:
    settings = get_app_settings()
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
                  docs_url=None if settings.is_production else "/docs")
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Required for the session cookie to cross origins (FE on Vercel, BE on Render) —
        # the browser only sends/accepts cookies on a cross-site fetch when both this is
        # true AND allow_origins is an explicit list (never "*", which settings.cors_origins
        # already satisfies).
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Response-Time"],
    )
    install_http_layer(app)
    app.middleware("http")(usage_scope)

    auth = [Depends(require_api_key)]
    app.include_router(intel_router, dependencies=auth)
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(events.router)
    mount_uploads(app, UPLOAD_DIR)

    @app.get("/api/health", include_in_schema=False)
    def health():
        with sa.begin() as conn:
            conn.execute(select(literal(1)))
        return {"ok": True}

    _mount_spa(app)
    return app


app = create_app()
