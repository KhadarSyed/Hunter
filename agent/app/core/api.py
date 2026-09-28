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

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import AppSettings, get_app_settings

logger = logging.getLogger("hunter.api")

REQUEST_ID_HEADER = "X-Request-ID"
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


def require_api_key(settings: SettingsDep, key: Annotated[str | None, Depends(_api_key_header)] = None) -> None:
    """Reject requests without the configured API key. No-op when API_KEY is unset (dev)."""
    if settings.api_key and not (key and secrets.compare_digest(key, settings.api_key)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key",
                            headers={"WWW-Authenticate": "APIKey"})


async def require_ws_api_key(ws: WebSocket) -> None:
    """WebSocket variant (browsers cannot set headers on WS): ?api_key=... query param."""
    expected = get_app_settings().api_key
    given = ws.query_params.get("api_key") or ws.headers.get("x-api-key") or ""
    if expected and not secrets.compare_digest(given, expected):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")


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
