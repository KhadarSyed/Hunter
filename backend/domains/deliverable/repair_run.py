"""The Fix button: the deck's repair agent run again on a finished deliverable, scoped to the panel it was pressed
on (deck checks, or the brief), its progress streamed into the run's own log like the run itself."""
from __future__ import annotations

import contextvars
import logging
import threading
from pathlib import Path

from ...core import store, writing_locale
from ...core.events import broadcast
from ..deckstudio import fixer
from . import deck_store, engine

logger = logging.getLogger(__name__)


def has_repair_context(run: dict) -> bool:
    """Whether the Fix button can work on this run: runs from before repairs were saved with the deck cannot."""
    return bool(run.get("deck_dir")) and (Path(run["deck_dir"]) / fixer.CONTEXT_FILE).exists()


def start(project_id: int, run_id: int, scope: str, *, llm=None, threaded: bool = True) -> None:
    run = store.get_deliverable_run(run_id) or {}
    if run.get("status") != "completed":
        raise engine.RunBusy("Only a finished deliverable can be repaired")
    deck_store.restore(run)             # after a restart the deck is written back from Postgres
    if not has_repair_context(run):
        raise FileNotFoundError("This run was made before repairs were saved with the deck; regenerate it once")
    if llm is None:
        try:
            from ...core.llm_provider import get_llm_client
            llm = get_llm_client()
        except Exception as e:      # the agent still repairs what needs no drafting (logos, icons, screenshots)
            logger.warning("[repair:%s] no LLM: %s", run_id, type(e).__name__)
    # read before the run is marked running: a failure here must not leave it 'running' with no thread behind it
    llm = writing_locale.with_locale(llm, writing_locale.project_geography(store.get_project(project_id)))
    with engine._lock:
        if engine.design_lock.locked():
            raise engine.RunBusy("The deck is being recoloured; try Fix again in a minute")
        if store.get_active_deliverable_run(project_id):
            raise engine.RunBusy("A deliverable run or repair is already in progress")
        store.update_deliverable_run(run_id, status="running", stage="repair")
    if threaded:
        threading.Thread(target=contextvars.copy_context().run, args=(_repair, project_id, run_id, scope, llm), daemon=True).start()
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
    with engine.design_lock:        # no recolour re-exports the deck while the repair rewrites it
        run = _repair_locked(project_id, run_id, scope, llm)
        # finished_at stays the run's own: typical run durations (the progress estimate) are measured from it
        store.update_deliverable_run(run_id, status="completed", stage="repair",
                                     **({"stages_json": run.stages} if run else {}))
    if run:
        deck_store.persist(run_id, (store.get_deliverable_run(run_id) or {}).get("deck_dir"))
        run.progress(100, "Repairs finished")
    broadcast({"type": "deliverable_completed", "project_id": project_id, "run_id": run_id, "ready": True})


def _repair_locked(project_id: int, run_id: int, scope: str, llm) -> "engine._Run | None":
    """The repair itself; never raises, so the run is always set back to completed. None if setup failed."""
    run = None
    try:
        sections = {s["id"]: s for s in store.list_deliverable_sections(run_id)}
        stages = dict((store.get_deliverable_run(run_id) or {}).get("stages") or {})
        run = engine._Run(run_id, project_id)
        run.lines = list((sections.get("log") or {}).get("lines") or [])
        run.stages = stages
        run.stage("repair", "running")
        run.log(f"Fix requested for {'the brief' if scope == 'brief' else 'the deck checks' if scope == 'checks' else 'everything open'}")
        deck_dir = Path(store.get_deliverable_run(run_id)["deck_dir"])
        spec, context = fixer.load(deck_dir)
        repair = fixer.Repair(spec, context, llm, deck_dir, log=run.log)
        studio = sections.get("studio") or {"id": "studio", "rq_id": None, "module": "studio", "title": "Deck"}
        # the deck is checked again by today's rules (a check that changed since the run is then repaired); the
        # stored checks that need the exported PPTX stay as they were
        fresh = fixer.validate_with(repair, None)
        names = {c["check"] for c in fresh}
        checks = fresh + [c for c in studio.get("validation") or []
                          if c["check"] not in names and not c["check"].startswith("Brief: ")]
        checks, rebuilt = fixer.run_repairs(repair, checks, scope)
        store.replace_deliverable_section(run_id, _studio_section(studio, repair.spec, checks, repair.checklist,
                                                                  (rebuilt or {}).get("report")))
        run.stage("repair", "done", f"{sum(c['status'] == 'pass' for c in checks)} of {len(checks)} checks pass")
    except Exception as e:      # the deck as it was stays available
        logger.exception("[repair:%s] failed", run_id)
        if run:
            run.stages["repair"] = "failed"
            try:
                run.log(f"Repair agent stopped: {type(e).__name__}: {e}")
            except Exception:   # recording the line must never stop the status write
                logger.exception("[repair:%s] could not record the failure line", run_id)
    return run
