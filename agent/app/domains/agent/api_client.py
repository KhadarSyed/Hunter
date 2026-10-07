"""The app's own /api/intel routes, called in-process as a real user. Stage logic lives in the routers, so the agent
goes through them: the same validation and the same project access checks as the UI (Ruling R1)."""
from __future__ import annotations

import time

from ...core import store
from ...core.auth import SESSION_COOKIE_NAME

JOB_POLL_SECONDS = 3
_DONE = ("completed", "failed", "cancelled")


class ToolError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, user_id: int):
        if not store.get_user_by_id(user_id):
            raise ToolError(f"user {user_id} does not exist")
        from fastapi.testclient import TestClient
        from ...core.api import get_app_settings
        from ...main import app                   # lazy: main imports the domains package
        token, _expires = store.create_session(user_id)
        self._token = token
        self._client = TestClient(app, raise_server_exceptions=False)
        self._client.cookies.set(SESSION_COOKIE_NAME, token)
        key = get_app_settings().api_key
        self._headers = {"X-API-Key": key} if key else {}

    def call(self, method: str, path: str, **kw) -> dict:
        r = self._client.request(method, "/api/intel" + path, headers=self._headers, **kw)
        if r.status_code >= 400:
            raise ToolError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def wait_job(self, job_id: str, timeout: float) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.call("GET", f"/job/{job_id}")
            if job.get("status") in _DONE:
                return job
            time.sleep(JOB_POLL_SECONDS)
        raise ToolError(f"job {job_id} still running after {int(timeout)}s")

    def close(self) -> None:
        store.delete_session(self._token)
        self._client.close()
