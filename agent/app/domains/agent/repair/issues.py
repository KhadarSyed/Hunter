"""Where problems become issues: engine failures, QC flags that survived repair, browser QA findings, progress
calibration and user reports from the copilot. Issues are deduplicated by fingerprint and always redacted."""
from __future__ import annotations

import hashlib
import re
import traceback

from ....core import store
from ..redact import redact

TRACE_LINES = 40
_DIGITS = re.compile(r"\d+")


def fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(_DIGITS.sub("#", p or "") for p in parts).encode("utf-8")).hexdigest()[:16]


def _clean(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def file_issue(source: str, kind: str, title: str, detail: dict, project_id: int | None = None,
               status: str = "open") -> tuple[int, bool]:
    """status "triage" holds an issue until a super admin sends it to the fixer (user reports: their text becomes the
    fixer's instructions)."""
    title = redact(title)[:300]
    return store.file_issue_row(fingerprint(source, kind, title), source, kind, title, _clean(detail), project_id, status)


def from_exception(stage: str, exc: BaseException, project_id: int | None) -> int:
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).splitlines()[-TRACE_LINES:]
    first = str(exc).splitlines()[0] if str(exc) else ""
    issue_id, _new = file_issue("engine", "exception", f"{stage}: {type(exc).__name__}: {first}",
                                {"stage": stage, "type": type(exc).__name__, "message": str(exc)[:1000],
                                 "trace": "\n".join(trace)}, project_id)
    return issue_id


def check_progress_calibration(run_id: int, tolerance: float = 0.5, weights: dict | None = None) -> int | None:
    if weights is None:
        from ...deliverable.engine import STAGE_WEIGHTS
        weights = STAGE_WEIGHTS
    timings = next((s for s in store.list_deliverable_sections(run_id) if s["id"] == "timings"), None)
    if not timings or not timings.get("stages"):
        return None
    spent = {k: max(0.0, v[1] - v[0]) for k, v in timings["stages"].items() if v and len(v) == 2}
    total_t, total_w = sum(spent.values()), sum(weights.get(k, 0) for k in spent)
    if not total_t or not total_w:
        return None
    share = {k: (spent[k] / total_t, weights.get(k, 0) / total_w) for k in spent}
    gap = sum(abs(m - w) for m, w in share.values())
    if gap <= tolerance:
        return None
    worst = sorted(share, key=lambda k: -abs(share[k][0] - share[k][1]))[:3]
    issue_id, _ = file_issue("engine", "progress_calibration", "Progress bar weights do not match real stage times",
                             {"run_id": run_id, "gap": round(gap, 2), "worst": worst,
                              "measured_share": {k: round(m, 3) for k, (m, _w) in share.items()}})
    return issue_id
