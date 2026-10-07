"""Application factory.

`create_app()` wires the two products onto one FastAPI app:
- Intelligence Platform: `domains` routers under /api/intel
- Brief-to-Deck: `deck.router` under /api
plus the shared /ws event socket, the HTTP layer (request ids, timing, error envelope),
and the built React SPA from agent/static/ (so one server on :8002 serves everything).

Run: python -m uvicorn agent.app.main:app --host 0.0.0.0 --port 8002
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # before importing modules that read os.environ at import time

from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .core import events, jobs, store  # noqa: E402
from .core.api import install_http_layer, require_api_key  # noqa: E402
from .core.auth import seed_super_admin_if_missing  # noqa: E402
from .core.config import (  # noqa: E402
    AGENT_DIR,
    UPLOAD_DIR,
    ensure_dirs,
    get_app_settings,
    load_settings,
)
from .deck import memory  # noqa: E402
from .deck import router as deck  # noqa: E402
from .domains import router as intel_router  # noqa: E402
from .domains.auth.router import router as auth_router  # noqa: E402

logger = logging.getLogger("hunter")

STATIC_DIR = AGENT_DIR / "static"
GZIP_MIN_BYTES = 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    memory.init_db()
    store.init_intelligence_db()
    seed_super_admin_if_missing()
    store.cancel_stale_running_jobs()
    memory.mark_interrupted_runs()
    store.fail_interrupted_deliverable_runs()
    ensure_dirs(load_settings())
    events.bind_loop(asyncio.get_running_loop())
    from .domains.agent import autopilot
    autopilot.resume_all()
    deck.start_watcher()
    logger.info("Hunter started (%s)", get_app_settings().environment)
    try:
        yield
    finally:
        deck.stop_watcher()
        events.bind_loop(None)
        jobs.runner.shutdown(wait=False)
        logger.info("Hunter stopped")


def mount_uploads(app: FastAPI, upload_dir: Path) -> None:
    """Publicly serve only the avatars subdirectory — briefs, QC exports, and
    other upload types under UPLOAD_DIR must never be web-accessible."""
    avatars_dir = upload_dir / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads/avatars", StaticFiles(directory=str(avatars_dir)), name="uploads-avatars")


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

    auth = [Depends(require_api_key)]
    app.include_router(intel_router, dependencies=auth)
    app.include_router(deck.router, dependencies=auth)
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(events.router)
    mount_uploads(app, UPLOAD_DIR)

    @app.get("/api/health", include_in_schema=False)
    def health():
        conn = store._conn()
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        return {"ok": True}

    _mount_spa(app)
    return app


app = create_app()
