"""Real-time events: the shared /ws WebSocket and a thread-safe broadcast().

Routers, services and background jobs call `broadcast({...})` from any thread; the
message is scheduled onto the server's event loop and pushed to the connected clients
allowed to see it. Before the app starts (e.g. in unit tests) broadcast() is a silent no-op.

Access: a socket is opened only with a signed ticket from GET /api/auth/ws-ticket (or, same-origin, the
session cookie), and each message reaches only the users who may open the project it is about — found from
its project_id, job_id or report_id. A project-scoped message whose project cannot be found goes to Super
Admins only; messages about no project (Brief-to-Deck chat and history) go to every signed-in user.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from starlette.concurrency import run_in_threadpool

from . import ws_tickets

logger = logging.getLogger(__name__)

MAX_SOCKETS_PER_USER = 8          # a user's oldest socket closes when a new one goes past this
_PROJECT_SCOPED = ("intel_", "qc_", "deliverable_", "agent_", "project_")

Audience = Callable[[dict], bool]


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[WebSocket, dict] = {}      # socket -> its signed-in user
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, user: dict) -> None:
        await ws.accept()
        async with self._lock:
            mine = [s for s, u in self.connections.items() if u["id"] == user["id"]]
            self.connections[ws] = user
        for old in mine[:max(0, len(mine) + 1 - MAX_SOCKETS_PER_USER)]:
            await self.disconnect(old)
            try:
                await old.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:  # already gone
                pass

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.connections.pop(ws, None)

    async def send_all(self, message: dict, audience: Audience | None = None) -> None:
        dead = []
        for ws, user in list(self.connections.items()):
            if audience is not None and not audience(user):
                continue
            try:
                await ws.send_json(message)
            except Exception:  # client went away mid-send
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Called from the app lifespan: enables (loop) / disables (None) broadcasting."""
    global _loop
    _loop = loop


def _project_of(message: dict) -> dict | None:
    from . import store  # local: store imports every domain, which imports this module
    project_id = message.get("project_id")
    if not project_id and message.get("job_id"):
        project_id = (store.get_job(str(message["job_id"])) or {}).get("project_id")
    if not project_id and message.get("report_id"):
        project_id = (store.get_qc_report(int(message["report_id"])) or {}).get("project_id")
    return store.get_project(int(project_id)) if project_id else None


def audience_for(message: dict) -> Audience:
    """Who may receive `message`: a function of the receiving socket's user."""
    from .auth import can_access_project
    try:
        project = _project_of(message)
    except Exception as e:  # a lookup failure never widens delivery
        logger.warning("broadcast %s: project lookup failed (%s)", message.get("type"), e)
        project = None
    if project is not None:
        return lambda user: can_access_project(project, user)
    scoped = any(k in message for k in ("project_id", "job_id", "report_id")) or \
        str(message.get("type", "")).startswith(_PROJECT_SCOPED)
    if scoped:
        return lambda user: user["role"] == "super_admin"
    return lambda user: True


def broadcast(message: dict) -> None:
    """Push a message to the clients allowed to see it. Safe to call from worker threads."""
    if _loop is None or _loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.send_all(message, audience_for(message)), _loop)
    except RuntimeError:  # loop shutting down
        logger.debug("broadcast dropped during shutdown: %s", message.get("type"))


def _socket_user(ticket: str | None, session_token: str | None) -> dict | None:
    from . import store
    user_id = ws_tickets.verify(ticket)
    if user_id is not None:
        user = store.get_user_by_id(user_id)
        return user if user and not user.get("archived_at") else None
    return store.get_session_user(session_token) if session_token else None


router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    from .auth import SESSION_COOKIE_NAME
    user = await run_in_threadpool(_socket_user, ws.query_params.get("ticket"), ws.cookies.get(SESSION_COOKIE_NAME))
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await manager.connect(ws, user)
    try:
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as e:  # a malformed frame ends this socket, never the server
        logger.info("websocket closed: %s", type(e).__name__)
        try:
            await ws.close(code=status.WS_1003_UNSUPPORTED_DATA)
        except Exception:  # already closed
            pass
    finally:
        await manager.disconnect(ws)
