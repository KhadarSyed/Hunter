"""The Fix button: the deck's repair agent run again on a finished deliverable, scoped to the panel it was pressed
on (deck checks, or the brief), its progress streamed into the run's own log like the run itself."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from ...core import store, writing_locale
from ...core.events import broadcast
from ..deckstudio import fixer
from . import engine

logger = logging.getLogger(__name__)


def has_repair_context(run: dict) -> bool:
    """Whether the Fix button can work on this run: runs from before repairs were saved with the deck cannot."""
    return bool(run.get("deck_dir")) and (Path(run["deck_dir"]) / fixer.CONTEXT_FILE).exists()


def start(project_id: int, run_id: int, scope: str, *, llm=None, threaded: bool = True) -> None:
    run = store.get_deliverable_run(run_id) or {}
    if run.get("status") != "completed":
        raise engine.RunBusy("Only a finished deliverable can be repaired")
    if not has_repair_context(run):
        raise FileNotFoundError("This run was made before repairs were saved with the deck; regenerate it once")
    with engine._lock:
        if store.get_active_deliverable_run(project_id):
            raise engine.RunBusy("A deliverable run or repair is already in progress")
        store.update_deliverable_run(run_id, status="running", stage="repair")
    if llm is None:
        try:
            from ...core.anthropic_client import get_llm_client
            llm = get_llm_client()
        except Exception as e:      # the agent still repairs what needs no drafting (logos, icons, screenshots)
            logger.warning("[repair:%s] no LLM: %s", run_id, type(e).__name__)
    llm = writing_locale.with_locale(llm, writing_locale.project_geography(store.get_project(project_id)))
    if threaded:
        threading.Thread(target=_repair, args=(project_id, run_id, scope, llm), daemon=True).start()
    else:
        _repair(project_id, run_id, scope, llm)


def _studio_section(studio: dict, spec, checks: list[dict], rows: list[dict], report: list[dict] | None) -> dict:
    qc = {r["slide_id"]: r for r in report or []}
    old = {s["id"]: s for s in studio.get("slides") or []}
    return {**studio, "validation": checks, "checklist": rows,
            "scorecard": {k: sum(1 for r in rows if r["status"] == k) for k in ("covered", "partial", "missing")},
            "slides": [{"id": s.id, "type": s.type, "treatment": s.treatment, "reference": s.reference,
                        "source": (qc.get(s.id) or old.get(s.id) or {}).get("source", "template"),
                        "qc": (qc.get(s.id) or old.get(s.id) or {}).get("qc", [])} for s in spec.slides]}


def _repair(project_id: int, run_id: int, scope: str, llm) -> None:
    run = engine._Run(run_id, project_id)
    sections = {s["id"]: s for s in store.list_deliverable_sections(run_id)}
    run.lines = list((sections.get("log") or {}).get("lines") or [])
    run.stages = dict((store.get_deliverable_run(run_id) or {}).get("stages") or {})
    try:
        run.stage("repair", "running")
        run.log(f"Fix requested for {'the brief' if scope == 'brief' else 'the deck checks' if scope == 'checks' else 'everything open'}")
        deck_dir = Path(store.get_deliverable_run(run_id)["deck_dir"])
        spec, context = fixer.load(deck_dir)
        repair = fixer.Repair(spec, context, llm, deck_dir, log=run.log)
        studio = sections.get("studio") or {"id": "studio", "rq_id": None, "module": "studio", "title": "Deck"}
        checks = studio.get("validation") or fixer.validate_with(repair, None)
        checks, rebuilt = fixer.run_repairs(repair, checks, scope)
        store.replace_deliverable_section(run_id, _studio_section(studio, repair.spec, checks, repair.checklist,
                                                                  (rebuilt or {}).get("report")))
        run.stage("repair", "done", f"{sum(c['status'] == 'pass' for c in checks)} of {len(checks)} checks pass")
    except Exception as e:      # the deck as it was stays available
        logger.exception("[repair:%s] failed", run_id)
        run.stages["repair"] = "failed"
        run.log(f"Repair agent stopped: {type(e).__name__}: {e}")
    # finished_at stays the run's own: typical run durations (the progress estimate) are measured from it
    store.update_deliverable_run(run_id, status="completed", stage="repair", stages_json=run.stages)
    run.progress(100, "Repairs finished")
    broadcast({"type": "deliverable_completed", "project_id": project_id, "run_id": run_id, "ready": True})
