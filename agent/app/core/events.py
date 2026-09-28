"""Real-time events: the shared /ws WebSocket and a thread-safe broadcast().

Routers, services and background jobs call `broadcast({...})` from any thread; the
message is scheduled onto the server's event loop and pushed to every connected
client. Before the app starts (e.g. in unit tests) broadcast() is a silent no-op.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.connections.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self.connections:
                self.connections.remove(ws)

    async def send_all(self, message: dict) -> None:
        dead = []
        for ws in list(self.connections):
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


def broadcast(message: dict) -> None:
    """Push a message to all WebSocket clients. Safe to call from worker threads."""
    if _loop is None or _loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.send_all(message), _loop)
    except RuntimeError:  # loop shutting down
        logger.debug("broadcast dropped during shutdown: %s", message.get("type"))


router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(ws)
