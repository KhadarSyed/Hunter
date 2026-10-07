"""Git worktrees for proposed fixes: each fix is made on its own branch in its own folder under DATA_DIR/autofix,
tested there against a throwaway data dir, and merged into the main checkout only on apply."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ....core import config

OUTPUT_TAIL = 8000
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
    path = config.DATA_DIR / "autofix" / branch.replace("/", "-")
    path.parent.mkdir(parents=True, exist_ok=True)
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path), base)
    if (repo / TESTS_DIR).is_dir():
        shutil.copytree(repo / TESTS_DIR, path / TESTS_DIR, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    return Worktree(path=path, branch=branch, base=base)


def run(wt: Worktree, args: list[str], timeout: int = 1800, env_extra: dict | None = None,
        cwd_rel: str = "") -> tuple[int, str]:
    data = tempfile.mkdtemp(prefix="autofix_data_")
    env = {**os.environ, "HUNTER_AGENT_DATA_DIR": data, **(env_extra or {})}
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
    return _git(wt.path, "diff", "--cached", wt.base, "--", ".", f":(exclude){TESTS_DIR.as_posix()}")


def commit(wt: Worktree, message: str) -> str:
    _stage(wt)
    _git(wt.path, "commit", "-q", "-m", message)
    return _git(wt.path, "rev-parse", "HEAD")


def tree_clean(repo: Path | None = None) -> bool:
    return _git(repo or config.REPO_ROOT, "status", "--porcelain", "--untracked-files=no") == ""


def merge(branch: str, repo: Path | None = None) -> str:
    repo = repo or config.REPO_ROOT
    _git(repo, "merge", "--no-ff", "--no-edit", branch)
    return _git(repo, "rev-parse", "HEAD")


def revert(sha: str, repo: Path | None = None) -> str:
    repo = repo or config.REPO_ROOT
    _git(repo, "revert", "--no-edit", "-m", "1", sha)
    return _git(repo, "rev-parse", "HEAD")


def remove(wt: Worktree, repo: Path | None = None) -> None:
    if (config.DATA_DIR / "autofix").resolve() not in wt.path.resolve().parents:
        raise RuntimeError(f"refusing to remove {wt.path}: not an autofix worktree")
    _git(repo or config.REPO_ROOT, "worktree", "remove", "--force", str(wt.path))
