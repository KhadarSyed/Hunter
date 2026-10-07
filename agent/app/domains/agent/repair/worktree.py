"""Git worktrees for proposed fixes: each fix is made on its own branch in its own folder under DATA_DIR/autofix,
tested there against a throwaway data dir, and merged into the main checkout only on apply."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ....core import config

OUTPUT_TAIL = 8000
# Only what a test process needs to start (Windows and Node); nothing secret is ever passed to code the fixer writes
_ENV_KEEP = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE",
             "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "PYTHONIOENCODING", "PYTHONUTF8", "LANG"}
_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|ENDPOINT|CLIENT_ID|DATABASE_URL", re.I)
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
TESTS_DIR = Path("agent") / "tests"


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    base: str


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:400]}")
    return r.stdout.strip()


def create(issue_id: int, repo: Path | None = None) -> Worktree:
    repo = repo or config.REPO_ROOT
    branch = f"autofix/{issue_id}-{int(time.time())}"
    path = config.AUTOFIX_DIR / branch.replace("/", "-")
    path.parent.mkdir(parents=True, exist_ok=True)
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path), base)
    if (repo / TESTS_DIR).is_dir():
        shutil.copytree(repo / TESTS_DIR, path / TESTS_DIR, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    return Worktree(path=path, branch=branch, base=base)


def _secret_names() -> set[str]:
    """Secret-looking names in this process and in the repo's .env (names only, never values)."""
    names = {k for k in os.environ if _SECRET_NAME.search(k)}
    env_file = config.REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if (m := _ENV_LINE.match(line)) and _SECRET_NAME.search(m.group(1)):
                names.add(m.group(1))
    return names


def child_env(data_dir: str, extra: dict | None = None) -> dict:
    """Allow-listed environment; every secret name is present but empty, so a test's load_dotenv() (which never
    overrides) cannot fill it in."""
    env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEEP}
    env.update({name: "" for name in _secret_names()})
    env.update({"HUNTER_AGENT_DATA_DIR": data_dir, "HUNTER_SUPERVISED": "0", "HUNTER_AUTOFIX": "0"})
    env.update(extra or {})
    return env


def run(wt: Worktree, args: list[str], timeout: int = 1800, env_extra: dict | None = None,
        cwd_rel: str = "") -> tuple[int, str]:
    data = tempfile.mkdtemp(prefix="autofix_data_")
    env = child_env(data, env_extra)
    cmd = [sys.executable if args[0] == "python" else args[0], *args[1:]]
    try:
        r = subprocess.run(cmd, cwd=wt.path / cwd_rel, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr)[-OUTPUT_TAIL:]
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    finally:
        shutil.rmtree(data, ignore_errors=True)


def _stage(wt: Worktree) -> None:
    """agent/tests is git-ignored, so the fix's test is never staged; the diff excludes it explicitly as well."""
    _git(wt.path, "add", "-A")


def diff(wt: Worktree) -> str:
    _stage(wt)
    return _git(wt.path, "diff", "--cached", "--no-renames", wt.base, "--", ".", f":(exclude){TESTS_DIR.as_posix()}")


def commit(wt: Worktree, message: str) -> str:
    _stage(wt)
    _git(wt.path, "commit", "-q", "-m", message)
    return _git(wt.path, "rev-parse", "HEAD")


def tree_clean(repo: Path | None = None) -> bool:
    return _git(repo or config.REPO_ROOT, "status", "--porcelain", "--untracked-files=no") == ""


def merge(branch: str, repo: Path | None = None) -> str:
    """Merge a fix branch; a merge that would conflict is refused before it touches the checkout, and any merge that
    still fails is aborted, so the user's tree is never left half-merged."""
    repo = repo or config.REPO_ROOT
    probe = subprocess.run(["git", "merge-tree", "--write-tree", "HEAD", branch], cwd=repo, capture_output=True, text=True)
    if probe.returncode != 0:
        raise RuntimeError("the fix conflicts with the current code")
    try:
        _git(repo, "merge", "--no-ff", "--no-edit", branch)
    except RuntimeError:
        subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)
        raise
    return _git(repo, "rev-parse", "HEAD")


def revert(sha: str, repo: Path | None = None) -> str:
    repo = repo or config.REPO_ROOT
    try:
        _git(repo, "revert", "--no-edit", "-m", "1", sha)
    except RuntimeError:
        subprocess.run(["git", "revert", "--abort"], cwd=repo, capture_output=True)
        raise
    return _git(repo, "rev-parse", "HEAD")


def remove(wt: Worktree, repo: Path | None = None) -> None:
    if config.AUTOFIX_DIR.resolve() not in wt.path.resolve().parents:
        raise RuntimeError(f"refusing to remove {wt.path}: not an autofix worktree")
    repo = repo or config.REPO_ROOT
    _git(repo, "worktree", "remove", "--force", str(wt.path))
    if wt.branch.startswith("autofix/"):            # the fix's own throwaway branch; never any other branch
        _git(repo, "branch", "-D", wt.branch)
