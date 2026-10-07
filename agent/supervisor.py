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
        if code != RESTART_CODE:
            return code


if __name__ == "__main__":
    raise SystemExit(main())
