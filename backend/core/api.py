"""HTTP-layer plumbing shared by every router: middleware, error envelope, response
model base class, and FastAPI dependencies (settings, API-key auth).

Error envelope (every non-2xx JSON response):
    {"detail": <message or validation errors>,
     "error": {"code": "not_found", "message": "...", "request_id": "..."}}
`detail` is kept so FastAPI-style clients keep working.
"""
from __future__ import annotations

import logging
import secrets
import time
import uuid
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import AppSettings, get_app_settings

logger = logging.getLogger("hunter.api")

REQUEST_ID_HEADER = "X-Request-ID"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_STATUS_CODES = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    409: "conflict", 422: "validation_error", 429: "rate_limited", 503: "unavailable",
}


# ─── Response models ─────────────────────────────────────────────────────────

class ApiModel(BaseModel):
    """Base for response models: declared fields are typed/documented in OpenAPI;
    undeclared fields pass through, so adding a model never drops data the UI uses."""

    model_config = ConfigDict(extra="allow", from_attributes=True)


class OkResponse(ApiModel):
    ok: bool = True


# ─── Dependencies ────────────────────────────────────────────────────────────

SettingsDep = Annotated[AppSettings, Depends(get_app_settings)]

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(settings: SettingsDep, request: Request,
                    key: Annotated[str | None, Depends(_api_key_header)] = None) -> None:
    """Reject requests that carry neither the configured API key (scripts) nor a live session cookie (the app's own
    pages, which never send the key). No-op when API_KEY is unset (dev)."""
    if not settings.api_key or (key and secrets.compare_digest(key, settings.api_key)):
        return
    from . import store                       # local: store imports every domain
    from .auth import SESSION_COOKIE_NAME
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token and store.get_session_user(token):
        return
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key",
                        headers={"WWW-Authenticate": "APIKey"})


# ─── Middleware + error handlers ─────────────────────────────────────────────

def _envelope(request: Request, status_code: int, message: str, detail: Any = None,
              headers: dict[str, str] | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    body = {
        "detail": message if detail is None else detail,
        "error": {"code": _STATUS_CODES.get(status_code, f"http_{status_code}"), "message": message,
                  "request_id": request_id},
    }
    return JSONResponse(jsonable_encoder(body), status_code=status_code,
                        headers={**(headers or {}), REQUEST_ID_HEADER: request_id})


def install_http_layer(app: FastAPI) -> None:
    """Attach request-id/timing middleware and the error envelope handlers to `app`."""

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        if request.url.path.startswith("/api"):
            logger.info("%s %s -> %s %.0fms [%s]", request.method, request.url.path,
                        response.status_code, elapsed_ms, request.state.request_id)
        return response

    @app.middleware("http")
    async def reject_cross_site_writes(request: Request, call_next):
        # CSRF guard: the session cookie is SameSite=None in production, so a write from a foreign page
        # would carry it. Browsers always send Origin on such writes; requests without one (server-to-server,
        # tests) pass. Same-host origins (the SPA served by this backend) pass too.
        origin = request.headers.get("origin")
        if (origin and request.method in _UNSAFE_METHODS
                and origin.rstrip("/") not in get_app_settings().cors_origins
                and urlsplit(origin).netloc != request.headers.get("host")):
            return _envelope(request, 403, "Cross-origin request refused")
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        # Some routes raise HTTPException(400, <dict>) — keep structured details intact.
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _envelope(request, exc.status_code, message, detail=exc.detail, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _envelope(request, 422, "Request validation failed", detail=exc.errors())

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s [%s]", request.method, request.url.path,
                         getattr(request.state, "request_id", ""))
        return _envelope(request, 500, "Internal server error")
