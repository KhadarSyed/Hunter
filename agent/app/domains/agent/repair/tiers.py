"""Which proposed fixes may apply themselves. Design-only changes (deck templates, Tailwind classes, chart styling
constants, prompt wording) auto-apply behind a health check; logic waits in the Fixes inbox; secrets, config, auth,
migrations, dependencies, deletions and the agent's own code are never applied.

Every rule fails closed: a change the checks cannot prove is design-only goes to the inbox."""
from __future__ import annotations

import ast
import re
from fnmatch import fnmatch

NEVER = (".env*", "*/.env*", "agent/app/core/auth.py", "agent/app/domains/auth/*", "agent/app/core/db.py",
         "agent/app/core/config.py", "requirements*.txt", "pyproject.toml", "web/package.json", "web/package-lock.json",
         "agent/data/*", "agent/app/domains/agent/*", "agent/supervisor.py", "*.ps1", "*.bat", "*.sh")
AUTO_ANY = ("agent/app/domains/deckstudio/templates/*",)
AUTO_CLASSNAME = ("web/src/*.tsx",)
AUTO_CONSTANTS = ("agent/app/domains/deckstudio/charts.py", "agent/app/domains/deliverable/style.py")
IGNORED = ("agent/tests/*",)
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_CLASSNAME = re.compile(r'className=("[^"]*"|\'[^\']*\'|\{`[^`$]*`\})')
_CONSTANT = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.+)$")


def _match(path: str, globs) -> bool:
    return any(fnmatch(path, g) for g in globs)        # fnmatch's * also matches '/'


def parse(diff: str) -> list[dict]:
    """Files with their hunks; each hunk keeps removed/added lines and the new-file line number of each added line."""
    files, cur, hunk, new_no = [], None, None, 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            cur = {"path": line.split(" b/", 1)[-1], "deleted": False, "new": False, "renamed": False,
                   "added": [], "removed": [], "hunks": []}
            files.append(cur)
            hunk = None
        elif cur is None:
            continue
        elif line.startswith("deleted file mode"):
            cur["deleted"] = True
        elif line.startswith("new file mode"):
            cur["new"] = True
        elif line.startswith(("rename from", "rename to", "copy from", "copy to")):
            cur["renamed"] = True
        elif m := _HUNK.match(line):
            hunk = {"removed": [], "added": [], "added_at": []}
            cur["hunks"].append(hunk)
            new_no = int(m.group(2))
        elif line.startswith(("+++", "---", "index ")) or hunk is None:
            continue
        elif line.startswith("+"):
            hunk["added"].append(line[1:])
            hunk["added_at"].append(new_no)
            cur["added"].append(line[1:])
            new_no += 1
        elif line.startswith("-"):
            hunk["removed"].append(line[1:])
            cur["removed"].append(line[1:])
        else:
            new_no += 1
    return files


def _classname_only(f: dict) -> bool:
    """Each changed line is paired with the line it replaces in the same hunk, and only className strings differ."""
    if not f["hunks"]:
        return False
    for h in f["hunks"]:
        if len(h["removed"]) != len(h["added"]) or not h["added"]:
            return False
        for old, new in zip(h["removed"], h["added"]):
            if "${" in new or "${" in old or "className=" not in new:
                return False
            if _CLASSNAME.sub("className=_", old) != _CLASSNAME.sub("className=_", new):
                return False
    return True


def _literal_constant(line: str) -> bool:
    m = _CONSTANT.match(line.strip())
    if not m:
        return False
    try:
        ast.literal_eval(m.group(2))
    except (ValueError, SyntaxError):
        return False
    return True


def _constants_only(f: dict) -> bool:
    lines = [l for l in f["added"] + f["removed"] if l.strip()]
    return bool(lines) and all(_literal_constant(l) for l in lines)


def _pure_string(line: str) -> bool:
    text = line.strip().rstrip(",").rstrip(")").strip()
    try:
        node = ast.parse(text, mode="eval").body
    except SyntaxError:
        return False
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _prompt_spans(source: str) -> list[tuple[int, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [(n.lineno, n.end_lineno) for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id.endswith("_PROMPT") for t in n.targets)]


def _prompt_only(f: dict, read_source) -> bool:
    """Only the wording of a *_PROMPT string changes: every changed line is a plain string literal and every added
    line sits inside a *_PROMPT assignment of the new file."""
    if not f["path"].endswith(".py") or f["new"] or read_source is None:
        return False
    changed = [l for l in f["added"] + f["removed"] if l.strip()]
    if not changed or not all(_pure_string(l) for l in changed):
        return False
    spans = _prompt_spans(read_source(f["path"]) or "")
    added_at = [n for h in f["hunks"] for n, text in zip(h["added_at"], h["added"]) if text.strip()]
    return bool(spans) and all(any(a <= n <= b for a, b in spans) for n in added_at)


def classify(diff: str, read_source=None) -> tuple[str, str]:
    files = [f for f in parse(diff) if not _match(f["path"], IGNORED)]
    if not files:
        return "never", "empty diff"
    for f in files:
        if f["deleted"]:
            return "never", f"deletes {f['path']}"
        if f["renamed"]:
            return "never", f"renames or copies {f['path']}"
        if _match(f["path"], NEVER):
            return "never", f"touches protected {f['path']}"
    for f in files:
        if _match(f["path"], AUTO_ANY):
            continue
        if _match(f["path"], AUTO_CLASSNAME) and _classname_only(f):
            continue
        if f["path"] in AUTO_CONSTANTS and _constants_only(f):
            continue
        if _prompt_only(f, read_source):
            continue
        return "inbox", f"logic change in {f['path']}"
    return "auto", "design-only change: " + ", ".join(f["path"] for f in files)
