"""Runs the backend and restarts it when it exits with RESTART_CODE: how an applied fix (or its rollback) takes effect.
Any other exit code stops the supervisor with that code."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

RESTART_CODE = 75


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", default="8002")
    a = ap.parse_args(argv)
    env = {**os.environ, "HUNTER_SUPERVISED": "1", "HUNTER_PORT": str(a.port)}
    cmd = [sys.executable, "-m", "uvicorn", "agent.app.main:app", "--host", a.host, "--port", str(a.port)]
    while True:
        code = subprocess.call(cmd, env=env)
        if code == RESTART_CODE:
            continue
        if _rollback_after_crash(code):
            continue                # the fix being verified broke startup; it is reverted, start again once
        return code


def _rollback_after_crash(code: int) -> bool:
    """A fix still being verified when the backend exits abnormally is reverted, so a bad merge never keeps the app
    down. Returns True when something was rolled back."""
    try:
        from agent.app.domains.agent.repair import apply
        return bool(apply.rollback_verifying(f"backend exited with code {code} after the fix was merged"))
    except Exception as e:      # the supervisor itself must keep its simple contract
        print(f"supervisor: rollback check failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    raise SystemExit(main())
