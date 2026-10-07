"""The fixer: an Azure OpenAI tool loop confined to a git worktree. Python issues need a test that fails before the
change and passes after it, plus a green suite; UI issues need a clean type-check here and pass their browser QA
re-check after apply (Ruling R3). Anything else is discarded."""
from __future__ import annotations

import fnmatch
import json
import logging
import re
import subprocess
from pathlib import Path

from ....core import config, store
from ..redact import redact
from . import tiers, worktree

logger = logging.getLogger(__name__)
MAX_TURNS = 30
READ_LIMIT = 60000
SEARCH_HITS = 200
OVERWRITE_MAX_LINES = 40          # existing files longer than this are changed with edit_file, never rewritten
MASS_DELETION_LINES = 30
SUITE = ["python", "-m", "pytest", "agent/tests", "-x", "-q", "-p", "no:cacheprovider",
         "--ignore=agent/tests/test_e2e_live_workflow.py"]
_REFUSED = (".env*", "*/.env*", "agent/data/*", ".git/*")
_SYSTEM = ("You fix one problem in the Hunter codebase (FastAPI backend in agent/app, React frontend in web/src). Work "
           "only through the tools. For a backend problem: FIRST write a pytest file at {test} that reproduces the "
           "problem and fails today; THEN change the code so it passes. For a UI problem: change web/src only. Keep "
           "the change minimal and in the style of the surrounding code. Change existing files with edit_file; write_file is only for new files. Do not touch .env, auth, migrations or "
           "dependencies. Stop calling tools when done.")


def _fn(name: str, desc: str, required: list[str], props: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "required": required, "properties": props}}}


_S = {"type": "string"}
_TOOLS = [_fn("read_file", "Read a repo file", ["path"], {"path": _S}),
          _fn("list_files", "List repo files matching a glob", ["glob"], {"glob": _S}),
          _fn("search", "Regex search in files matching a glob", ["pattern"], {"pattern": _S, "glob": _S}),
          _fn("write_file", "Create a new file (or replace a very short one) with this full content",
              ["path", "content"], {"path": _S, "content": _S}),
          _fn("edit_file", "Change an existing file: replace the exact text `old` (must occur once) with `new`",
              ["path", "old", "new"], {"path": _S, "old": _S, "new": _S}),
          _fn("run_test", "Run one pytest file", ["path"], {"path": _S})]


def _inside(wt, rel: str) -> Path | None:
    root = wt.path.resolve()
    target = (wt.path / rel).resolve()
    if root not in target.parents:
        return None
    relpath = target.relative_to(root).as_posix()
    return None if any(fnmatch.fnmatch(relpath, p) for p in _REFUSED) else target


def _tool(wt, name: str, args: dict) -> str:
    if name in ("read_file", "write_file", "edit_file", "run_test"):
        target = _inside(wt, str(args.get("path", "")))
        if target is None:
            return "refused: path is outside the worktree or protected"
        if name == "read_file":
            return redact(target.read_text(encoding="utf-8", errors="replace")[:READ_LIMIT]) if target.is_file() else "no such file"
        if name == "edit_file":
            if not target.is_file():
                return "refused: no such file; use write_file to create it"
            text = target.read_text(encoding="utf-8")
            if text.count(args.get("old", "")) != 1 or not args.get("old"):
                return "refused: `old` must match exactly one place in the file"
            target.write_text(text.replace(args["old"], args.get("new", ""), 1), encoding="utf-8")
            return "edited"
        if name == "write_file":
            if target.is_file() and len(target.read_text(encoding="utf-8", errors="replace").splitlines()) > OVERWRITE_MAX_LINES:
                return "refused: this file exists; change it with edit_file instead of rewriting it"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.get("content", ""), encoding="utf-8")
            return "written"
        code, out = worktree.run(wt, ["python", "-m", "pytest", str(args["path"]), "-q", "-p", "no:cacheprovider"])
        return f"exit {code}\n{out[-3000:]}"
    if name == "list_files":
        return "\n".join(p.relative_to(wt.path).as_posix() for p in wt.path.glob(args.get("glob", "**/*"))
                         if p.is_file() and ".git" not in p.parts)[:READ_LIMIT]
    if name == "search":
        rx, hits = re.compile(args.get("pattern", "")), []
        for p in wt.path.glob(args.get("glob") or "**/*.py"):
            if not p.is_file() or ".git" in p.parts or _inside(wt, p.relative_to(wt.path).as_posix()) is None:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p.relative_to(wt.path).as_posix()}:{n}: {line.strip()[:200]}")
        return redact("\n".join(hits[:SEARCH_HITS]))
    return f"unknown tool {name}"


def _mass_deletion(diff: str) -> str:
    """A fix that removes most of a file is a broken rewrite, not a fix."""
    for f in tiers.parse(diff):
        if len(f["removed"]) > MASS_DELETION_LINES and len(f["removed"]) > 2 * len(f["added"]):
            return f"the change removes most of {f['path']} ({len(f['removed'])} lines removed, {len(f['added'])} added)"
    return ""


def _converse(wt, llm, issue: dict, test_rel: str, ask: str, stop_when=None) -> None:
    detail = redact(json.dumps(issue.get("detail") or {}, default=str))[:6000]
    messages = [{"role": "system", "content": _SYSTEM.format(test=test_rel)},
                {"role": "user", "content": f"Problem: {redact(issue['title'])}\nSource: {issue['source']}\n"
                                            f"Detail: {detail}\n{ask}"}]
    for _ in range(MAX_TURNS):
        out = llm.chat_tools(messages, _TOOLS)
        if not out.get("tool_calls"):
            return
        messages.append(out["message"])
        for call in out["tool_calls"]:
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": _tool(wt, call["name"], call["arguments"])[:12000]})
            if stop_when and stop_when():
                return


OUTPUT_IN_NOTE = 800


def _discard(issue_id: int, wt, repo: Path, reason: str, output: str = "") -> dict:
    note = f"{reason}\n{output[-OUTPUT_IN_NOTE:]}" if output else reason
    store.set_issue_status(issue_id, "discarded", note.strip())
    worktree.remove(wt, repo)
    return {"status": "discarded", "fix_id": None, "reason": reason}


def _junction_node_modules(wt, repo: Path) -> None:
    src, dst = repo / "web" / "node_modules", wt.path / "web" / "node_modules"
    if src.is_dir() and (wt.path / "web").is_dir() and not dst.exists():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], capture_output=True)


def _pytest(wt, test_rel: str) -> tuple[int, str]:
    return worktree.run(wt, ["python", "-m", "pytest", test_rel, "-q", "-p", "no:cacheprovider"])


def propose(issue_id: int, llm, repo: Path | None = None, create_wt=worktree.create) -> dict:
    repo = repo or config.REPO_ROOT
    issue = store.get_issue(issue_id)
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        store.set_issue_status(issue_id, "needs_llm", "Azure OpenAI is not reachable")
        return {"status": "needs_llm", "fix_id": None, "reason": "Azure OpenAI is not reachable"}
    store.set_issue_status(issue_id, "fixing")
    wt = create_wt(issue_id, repo)
    ui = issue["source"] == "qa_browser"
    test_rel = f"agent/tests/test_autofix_{issue_id}.py"
    tests: dict[str, str] = {}
    try:
        if not ui:
            _converse(wt, llm, issue, test_rel, "First write only the test.",
                      stop_when=lambda: (wt.path / test_rel).exists())
            if not (wt.path / test_rel).exists():
                return _discard(issue_id, wt, repo, "no reproducing test was written")
            code, tests["red"] = _pytest(wt, test_rel)
            if code == 0:
                return _discard(issue_id, wt, repo, "the test does not reproduce the problem (it passes before the fix)")
        _converse(wt, llm, issue, test_rel, "Now make the change.")
        if not ui:
            code, tests["green"] = _pytest(wt, test_rel)
            if code != 0:
                return _discard(issue_id, wt, repo, "the fix does not make its test pass", tests["green"])
            code, out = worktree.run(wt, SUITE, timeout=3600)
            tests["suite"] = out[-1500:]
            if code != 0:
                return _discard(issue_id, wt, repo, "the full suite fails with the fix", out)
        else:
            _junction_node_modules(wt, repo)
            code, out = worktree.run(wt, ["cmd", "/c", "npx", "tsc", "--noEmit"], cwd_rel="web") \
                if (wt.path / "web").is_dir() else (0, "no web/ folder")
            tests["typecheck"] = out[-1500:]
            if code != 0:
                return _discard(issue_id, wt, repo, "the frontend no longer type-checks")
            tests["red"] = f"browser QA finding: {issue['kind']} ({(issue.get('detail') or {}).get('detail', '')})"[:500]
        diff = worktree.diff(wt)
        if not diff.strip():
            return _discard(issue_id, wt, repo, "no change was made")
        if broken := _mass_deletion(diff):
            return _discard(issue_id, wt, repo, broken)
        tier, why = tiers.classify(diff, read_source=lambda p: (wt.path / p).read_text(encoding="utf-8", errors="replace")
                                   if (wt.path / p).is_file() else None)
        worktree.commit(wt, f"fix: {issue['title'][:60]} (autofix #{issue_id})")
        fix_id = store.create_fix(issue_id, wt.branch, tier, diff, {**{k: v[-1500:] for k, v in tests.items()},
                                                                    "tier_reason": why})
        store.set_issue_status(issue_id, "proposed", f"fix {fix_id} ({tier})")
        return {"status": "proposed", "fix_id": fix_id, "reason": why}
    except Exception as e:      # a crashed attempt is recorded, never retried blindly
        logger.exception("fixer failed for issue %s", issue_id)
        return _discard(issue_id, wt, repo, f"fixer error: {type(e).__name__}")
