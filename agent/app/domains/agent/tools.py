"""Typed tools the autopilot and copilot call. Writes go through the app's routes (ApiClient); reads come from the
store. Every call records one agent_events row. Nothing here deletes anything."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ...core import config, store
from . import memory
from .api_client import ApiClient, ToolError  # noqa: F401  (ToolError re-exported)
from .status import project_status

logger = logging.getLogger(__name__)
MANUAL_GATES_KEY = "manual_gates"
INPUT_SUFFIXES = (".csv", ".xlsx", ".xls", ".docx", ".pdf")
DATASET_SUFFIXES = (".csv", ".xlsx", ".xls")
JOB_TIMEOUT = 1800
RUN_TIMEOUT = 5400
RUN_POLL_SECONDS = 10
_WORD = re.compile(r"[a-z]{4,}")
_CONTENT_TYPES = {".csv": "text/csv", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  ".xls": "application/vnd.ms-excel"}
_NO_ARGS = {"type": "object", "properties": {}}
_STR = {"type": "string"}


@dataclass
class ToolContext:
    project_id: int
    user_id: int
    actor: str
    api: object
    llm: object = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[ToolContext, dict], dict]
    costly: bool = False


TOOLS: dict[str, Tool] = {}


class _NeedsHuman(RuntimeError):
    pass


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


def tool_specs(names: list[str] | None = None) -> list[dict]:
    chosen = [TOOLS[n] for n in names] if names else list(TOOLS.values())
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in chosen]


def _short(args: dict | None) -> dict:
    return {k: (v if len(str(v)) < 200 else str(v)[:200] + "…") for k, v in (args or {}).items()}


def run_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    started = time.time()
    tool = TOOLS.get(name)
    try:
        if tool is None:
            raise ToolError(f"unknown tool {name!r}")
        out = {"ok": True, "result": tool.handler(ctx, args or {})}
    except _NeedsHuman as e:
        out = {"ok": False, "needs_human": True, "error": str(e)}
    except Exception as e:      # a failed tool is reported to the model, never raised into the loop
        logger.warning("tool %s failed: %s", name, e)
        out = {"ok": False, "error": str(e)[:500]}
    memory.record(ctx.project_id, ctx.actor, name, {"args": _short(args), "ok": out["ok"], "error": out.get("error"),
                                                   "seconds": round(time.time() - started, 1)})
    return out


def _gate(ctx: ToolContext, step: str) -> None:
    gates = next((m["value"] for m in store.list_memory(ctx.project_id, "preference") if m["key"] == MANUAL_GATES_KEY), [])
    if ctx.actor == "autopilot" and step in (gates or []):
        raise _NeedsHuman(f"{step} approval is kept manual for this project")


def _reviewer(ctx: ToolContext) -> str:
    return f"hunter-agent:{ctx.user_id}"


def _job(ctx: ToolContext, started: dict) -> dict:
    job = ctx.api.wait_job(started["job_id"], JOB_TIMEOUT)
    if job["status"] != "completed":
        raise ToolError(f"job {job['status']}: {job.get('error') or ''}"[:300])
    return job.get("result") or {}


# ── inputs ────────────────────────────────────────────────────────────────────────────────────────────────────────
def list_input_files(folder: str) -> list[str]:
    target = Path(folder).resolve()
    if not any(target == r.resolve() or r.resolve() in target.parents for r in config.AGENT_INPUT_ROOTS):
        raise ToolError(f"{folder} is outside the allowed input folders")
    if not target.is_dir():
        raise ToolError(f"{folder} is not a folder")
    return sorted(str(p) for p in target.iterdir() if p.is_file() and p.suffix.lower() in INPUT_SUFFIXES)


def suggest_mapping(files: list[str], rqs: list[dict]) -> dict[str, list[str]]:
    """Each dataset to the research question whose words its file name shares most; no overlap goes to the first
    question (an 'overall' export usually serves the headline question)."""
    words = {q["id"]: set(_WORD.findall((q.get("question") or "").lower())) for q in rqs}
    out = {}
    for f in files:
        stem = set(_WORD.findall(Path(f).stem.lower().replace("_", " ").replace("-", " ")))
        best = max(rqs, key=lambda q: len(stem & words[q["id"]]))
        out[f] = [best["id"] if stem & words[best["id"]] else rqs[0]["id"]]
    return out


def _strategy_questions(ctx) -> list[dict]:
    s = ctx.api.call("GET", f"/strategy/{ctx.project_id}")
    return [{"id": q.get("question_id"), "question": q.get("question")}
            for q in s["strategy"].get("research_question_queries") or []]


# ── handlers ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _status(ctx, _args):
    s = project_status(ctx.project_id)
    keep = ("id", "file_name", "record_count", "processing_status", "enrichment_status", "approval_status")
    return {**s, "datasets": [{k: d.get(k) for k in keep} for d in s["datasets"]]}


def _generate_scope(ctx, _args):
    project = ctx.api.call("GET", f"/projects/{ctx.project_id}")
    brief = (project.get("spec") or {}).get("raw_brief") or ""
    if not brief:
        raise ToolError("the project has no brief text")
    started = ctx.api.call("POST", "/spec/generate", json={"project_id": ctx.project_id, "raw_brief_text": brief,
                                                           "use_llm": True})
    return {"spec_id": _job(ctx, started).get("spec_id")}


def _approve_scope(ctx, _args):
    _gate(ctx, "scope")
    spec = store.get_latest_spec(ctx.project_id) or {}
    if not spec:
        raise ToolError("no scope to approve")
    ready = ctx.api.call("GET", f"/spec/{spec['id']}/readiness")
    if ready.get("blocking_issues"):
        raise _NeedsHuman(f"scope has blocking issues: {ready['blocking_issues']}")
    return ctx.api.call("POST", f"/spec/{spec['id']}/approve", json={"reviewer": _reviewer(ctx)})


def _run_research(ctx, _args):
    project = ctx.api.call("GET", f"/projects/{ctx.project_id}")
    _job(ctx, ctx.api.call("POST", "/research/start", json={"spec": project["spec"], "project_id": ctx.project_id}))
    return {"research": "completed"}


def _approve_brief(ctx, _args):
    _gate(ctx, "brief")
    made = ctx.api.call("POST", "/brief/generate", json={"project_id": ctx.project_id})
    ctx.api.call("POST", f"/brief/{made['brief_id']}/approve", json={"reviewer": _reviewer(ctx)})
    return {"brief_id": made["brief_id"]}


def _generate_strategy(ctx, _args):
    _job(ctx, ctx.api.call("POST", "/strategy/generate", json={"project_id": ctx.project_id}))
    return {"questions": _strategy_questions(ctx)}


def _approve_strategy(ctx, _args):
    _gate(ctx, "strategy")
    strategy = store.get_latest_strategy(ctx.project_id) or {}
    if not strategy:
        raise ToolError("no strategy to approve")
    return ctx.api.call("POST", f"/strategy/{strategy['id']}/approve", json={"reviewer": _reviewer(ctx)})


def _list_inputs(ctx, args):
    folder = args.get("folder") or next((m["value"] for m in store.list_memory(ctx.project_id, "fact")
                                         if m["key"] == "input_folder"), "")
    return {"folder": folder, "files": list_input_files(folder)}


def _upload_datasets(ctx, args):
    listing = _list_inputs(ctx, args)
    files = [f for f in listing["files"] if Path(f).suffix.lower() in DATASET_SUFFIXES]
    if not files:
        raise ToolError(f"no dataset files in {listing['folder']}")
    mapping = args.get("mapping") or suggest_mapping(files, _strategy_questions(ctx))
    uploaded = []
    for f, rq_ids in mapping.items():
        if f not in files:
            raise ToolError(f"{f} is not one of the input files")
        for rq in rq_ids:
            with open(f, "rb") as fh:
                r = ctx.api.call("POST", f"/dataset/upload?project_id={ctx.project_id}&research_question_id={rq}",
                                 files={"file": (Path(f).name, fh, _CONTENT_TYPES[Path(f).suffix.lower()])})
            uploaded.append({"file": Path(f).name, "rq": rq, "dataset_id": r["dataset_id"]})
    memory.remember(ctx.project_id, "decision", "dataset_mapping", {Path(f).name: v for f, v in mapping.items()})
    return {"uploaded": uploaded}


def _pending_dataset(ctx, args) -> int:
    if args.get("dataset_id"):
        return int(args["dataset_id"])
    pending = [d for d in store.get_datasets_by_project(ctx.project_id)
               if d.get("processing_status") == "done" and d.get("approval_status") != "approved"]
    if not pending:
        raise ToolError("no dataset is waiting for approval")
    return pending[0]["id"]


def _enrich_dataset(ctx, args):
    did = _pending_dataset(ctx, args)
    ctx.api.call("POST", f"/dataset/{did}/enrich")
    deadline = time.time() + JOB_TIMEOUT
    while time.time() < deadline:
        d = store.get_dataset_by_id(did)
        if d.get("enrichment_status") in ("done", "error"):
            return {"dataset_id": did, "enrichment_status": d["enrichment_status"]}
        time.sleep(RUN_POLL_SECONDS)
    raise ToolError(f"dataset {did} enrichment still running")


def _approve_dataset(ctx, args):
    _gate(ctx, "datasets")
    did = _pending_dataset(ctx, args)
    ctx.api.call("POST", f"/dataset/{did}/approve")
    return {"dataset_id": did}


def run_summary(run_id: int) -> dict:
    from ..deliverable.engine import run_payload
    payload = run_payload(run_id)
    run, sections = payload["run"], {s["id"]: s for s in payload["sections"]}
    studio = sections.get("studio") or {}
    log = (sections.get("log") or {}).get("lines") or []
    return {"run_id": run_id, "status": run["status"], "stage": run.get("stage"), "error": run.get("error"),
            "scorecard": studio.get("scorecard"), "checklist": studio.get("checklist"),
            "qc": [ln["message"] for ln in log if ln["message"].startswith("QC flag")][-20:],
            "log_tail": [ln["message"] for ln in log][-25:]}


def _run_deliverable(ctx, _args):
    run_id = ctx.api.call("POST", f"/deliverable/{ctx.project_id}/run", json={})["run_id"]
    deadline = time.time() + RUN_TIMEOUT
    while time.time() < deadline:
        if (store.get_deliverable_run(run_id) or {}).get("status") in ("completed", "failed"):
            return run_summary(run_id)
        time.sleep(RUN_POLL_SECONDS)
    raise ToolError(f"deliverable run {run_id} still running")


def _read_run(ctx, args):
    run = store.get_deliverable_run(int(args["run_id"])) if args.get("run_id") else store.get_latest_deliverable_run(ctx.project_id)
    if not run or run.get("project_id") != ctx.project_id:
        raise ToolError("no deliverable run for this project")
    return run_summary(run["id"])


def _remember(ctx, args):
    memory.remember(ctx.project_id, args["kind"], args["key"], args["value"])
    return {"saved": args["key"]}


for _tool in (
    Tool("project_status", "Where the project is: each pipeline step's state and the suggested next step.", _NO_ARGS, _status),
    Tool("generate_scope", "Generate the research scope from the project's brief (LLM, ~2 min).", _NO_ARGS,
         _generate_scope, costly=True),
    Tool("approve_scope", "Approve the latest scope when it has no blocking issues.", _NO_ARGS, _approve_scope),
    Tool("run_research", "Run background research for the project (~5-10 min).", _NO_ARGS, _run_research, costly=True),
    Tool("approve_brief", "Generate and approve the analyst brief (also approves background research).", _NO_ARGS,
         _approve_brief),
    Tool("generate_strategy", "Generate the search strategy and research questions (~5 min).", _NO_ARGS,
         _generate_strategy, costly=True),
    Tool("approve_strategy", "Approve the latest search strategy.", _NO_ARGS, _approve_strategy),
    Tool("list_input_files", "List the client's input files (brief, Meltwater exports) in the project's input folder.",
         {"type": "object", "properties": {"folder": _STR}}, _list_inputs),
    Tool("upload_datasets", "Upload the input folder's dataset files, each to the research questions it serves. "
         "mapping: {file path: [question ids]}; omitted means match by file name.",
         {"type": "object", "properties": {"folder": _STR, "mapping": {
             "type": "object", "additionalProperties": {"type": "array", "items": _STR}}}}, _upload_datasets, costly=True),
    Tool("enrich_dataset", "Enrich a parsed dataset with the LLM (small datasets only).",
         {"type": "object", "properties": {"dataset_id": {"type": "integer"}}}, _enrich_dataset, costly=True),
    Tool("approve_dataset", "Approve a parsed dataset.",
         {"type": "object", "properties": {"dataset_id": {"type": "integer"}}}, _approve_dataset),
    Tool("run_deliverable", "Build the deliverable: analyses, insights and the deck (~6-30 min).", _NO_ARGS,
         _run_deliverable, costly=True),
    Tool("read_run", "Read a deliverable run: status, error, scorecard, brief checklist, QC flags, log tail.",
         {"type": "object", "properties": {"run_id": {"type": "integer"}}}, _read_run),
    Tool("remember", "Save a project preference, decision, fact or fix to memory.",
         {"type": "object", "required": ["kind", "key", "value"], "properties": {
             "kind": {"type": "string", "enum": list(memory.MEMORY_KINDS)}, "key": _STR, "value": {}}}, _remember),
):
    register(_tool)


def _report_issue(ctx, args):
    from .repair import issues
    issue_id, new = issues.file_issue("user", "user_report", args["title"],
                                      {"page": args.get("page", ""), "detail": args.get("detail", "")}, ctx.project_id)
    return {"issue_id": issue_id, "new": new}


register(Tool("report_issue", "File a problem the user reports (a bug, an ugly slide, a wrong label, a faded page).",
              {"type": "object", "required": ["title"], "properties": {"title": _STR, "page": _STR, "detail": _STR}},
              _report_issue))


def _deck_dir(ctx) -> Path:
    run = store.get_latest_deliverable_run(ctx.project_id) or {}
    if run.get("status") != "completed" or not run.get("deck_dir"):
        raise ToolError("there is no finished deck to change yet")
    return Path(run["deck_dir"])


def _revise(ctx, args):
    from ..deckstudio import revise
    out = revise.revise_slide(_deck_dir(ctx), str(args["slide"]), args["instructions"], ctx.llm)
    if out["applied"]:
        memory.remember(ctx.project_id, "preference", f"slide_{out['slide_id']}", args["instructions"])
    return out


def _design(ctx, args):
    from ..deckstudio import revise
    out = revise.set_design(_deck_dir(ctx), args["changes"])
    if out["applied"]:
        memory.remember(ctx.project_id, "preference", "design_tokens", {k: args["changes"][k] for k in out["applied"]})
    return out


register(Tool("revise_slide", "Restyle one slide of the finished deck following the user's instructions "
              "(slide = number or id). Numbers must stay those in the data.",
              {"type": "object", "required": ["slide", "instructions"], "properties": {"slide": _STR, "instructions": _STR}},
              _revise, costly=True))
register(Tool("set_design", "Change the deck's colours (6-hex) or fonts and re-export it.",
              {"type": "object", "required": ["changes"], "properties": {"changes": {"type": "object"}}},
              _design, costly=True))
