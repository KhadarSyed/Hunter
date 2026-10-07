"""Which proposed fixes may apply themselves. Design-only changes (deck templates, Tailwind classes, chart styling
constants, prompt wording) auto-apply behind a health check; logic waits in the Fixes inbox; secrets, config, auth,
migrations, dependencies and deletions are never applied."""
from __future__ import annotations

import re
from fnmatch import fnmatch

NEVER = (".env*", "*/.env*", "agent/app/core/auth.py", "agent/app/domains/auth/*", "agent/app/core/db.py",
         "agent/app/core/config.py", "requirements*.txt", "pyproject.toml", "web/package.json", "web/package-lock.json",
         "agent/data/*")
AUTO_ANY = ("agent/app/domains/deckstudio/templates/*",)
AUTO_CLASSNAME = ("web/src/*.tsx",)
AUTO_CONSTANTS = ("agent/app/domains/deckstudio/charts.py", "agent/app/domains/deliverable/style.py")
IGNORED = ("agent/tests/*",)
_CLASSNAME = re.compile(r'className=(\{`[^`]*`\}|"[^"]*"|\'[^\']*\')')
_CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]*\s*=\s*[-\w.\"'(), \[\]{}:#]+$")
_STRING_LINE = re.compile(r"""^\s*[rbuf]*["'].*["']\)?,?\s*$""")


def _match(path: str, globs) -> bool:
    return any(fnmatch(path, g) for g in globs)        # fnmatch's * also matches '/'


def parse(diff: str) -> list[dict]:
    files, cur = [], None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            cur = {"path": line.split(" b/", 1)[-1], "deleted": False, "new": False, "added": [], "removed": []}
            files.append(cur)
        elif cur is None or line.startswith(("+++", "---", "@@", "index ")):
            continue
        elif line.startswith("deleted file mode"):
            cur["deleted"] = True
        elif line.startswith("new file mode"):
            cur["new"] = True
        elif line.startswith("+"):
            cur["added"].append(line[1:])
        elif line.startswith("-"):
            cur["removed"].append(line[1:])
    return files


def _classname_only(f: dict) -> bool:
    strip = lambda lines: sorted(_CLASSNAME.sub("className=_", l) for l in lines)
    return bool(f["added"] or f["removed"]) and strip(f["added"]) == strip(f["removed"])


def _constants_only(f: dict) -> bool:
    return all(_CONSTANT.match(l.strip()) for l in f["added"] + f["removed"] if l.strip())


def _prompt_only(f: dict, read_source) -> bool:
    if not f["path"].endswith(".py") or f["new"] or read_source is None:
        return False
    lines = [l for l in f["added"] + f["removed"] if l.strip()]
    return bool(lines) and all(_STRING_LINE.match(l) for l in lines) and "_PROMPT =" in (read_source(f["path"]) or "")


def classify(diff: str, read_source=None) -> tuple[str, str]:
    files = [f for f in parse(diff) if not _match(f["path"], IGNORED)]
    if not files:
        return "never", "empty diff"
    for f in files:
        if f["deleted"]:
            return "never", f"deletes {f['path']}"
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
