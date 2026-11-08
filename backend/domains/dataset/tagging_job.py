"""The Data set tagging job: content -> article tags -> guardrail themes -> approved RQs in order -> relations.
Resumable: every phase reads only what is still pending, each result is saved as it lands."""
from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from ...core import events, store
from ...core.jobs import runner
from ..deliverable.labels import theme_key
from ..memory import service as memory
from . import batching, repository as repo

logger = logging.getLogger(__name__)

CONTENT_WORKERS = 6
ALL = 1_000_000
HEADLINES_PER_LABEL = 2
_RUNNING: set[int] = set()
_STATE: dict[int, dict] = {}
_LOCK = threading.Lock()


class TaggingBusy(RuntimeError):
    pass


def is_tagging(project_id: int) -> bool:
    with _LOCK:
        return project_id in _RUNNING


def tagging_state(project_id: int) -> dict:
    with _LOCK:
        running, st = project_id in _RUNNING, dict(_STATE.get(project_id) or {})
    done, total = st.get("done", 0), st.get("total", 0)
    left = round((time.time() - st["phase_started"]) / done * (total - done) / 60, 1) if running and done else None
    return {"running": running, "phase": st.get("phase") if running else None, "done": done, "total": total,
            "minutes_left": left, "counts": repo.tagging_counts(project_id), "approval": repo.dataset_approval(project_id)}


def start_tagging(project_id: int, user: str | None = None, only_rq: str | None = None) -> str:
    """only_rq: re-tag that one approved RQ's rows needing it; the other phases are skipped."""
    with _LOCK:
        if project_id in _RUNNING:
            raise TaggingBusy("Tagging is already running for this project")
        _RUNNING.add(project_id)
    job_id = uuid.uuid4().hex
    try:
        store.create_job(job_id, project_id, "dataset_tagging")
        runner.submit(run_job, project_id, job_id, None, only_rq, name=f"dataset_tagging_{project_id}")
    except Exception:
        with _LOCK:
            _RUNNING.discard(project_id)
        raise
    return job_id


class _Progress:
    # Progress counts articles, not batches (a deliberate deviation from the spec's "batches": finer and comparable).
    def __init__(self, project_id: int, job_id: str):
        self.pid, self.job_id = project_id, job_id
        self.phase, self.total, self.done = "", 0, 0

    def begin(self, phase: str, total: int) -> None:
        from ..usage import service as usage
        usage.fill(sub_stage=phase)     # phases run one after another; their pools share this holder
        self.phase, self.total, self.done = phase, total, 0
        with _LOCK:
            _STATE[self.pid] = {"phase": phase, "done": 0, "total": total, "phase_started": time.time()}
        self._emit(f"{phase}: {total} to do")

    def advance(self, n: int = 1) -> None:
        self.done += n
        with _LOCK:
            _STATE[self.pid]["done"] = self.done
        self._emit(f"{self.phase}: {self.done}/{self.total}")

    def _emit(self, message: str) -> None:
        pct = int(self.done * 100 / self.total) if self.total else 100
        try:
            store.update_job(self.job_id, progress_pct=pct, progress_message=message)
            events.broadcast({"type": "dataset_tagging", "project_id": self.pid, "phase": self.phase,
                              "done": self.done, "total": self.total, "message": message})
        except Exception as e:      # progress is best effort; it must never stop the tagging
            logger.warning("tagging progress not sent: %s", e)


def _workers() -> int:
    return max(1, int(os.getenv("HUNTER_ENRICH_WORKERS", "8")))


def _parallel(fn, items: list, workers: int, on_result, on_error=None) -> None:
    """fn(item) on a pool; on_result(item, value) runs here as each lands. One failure is logged, not raised."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(contextvars.copy_context().run, fn, it): it for it in items}
        for f in as_completed(futures):
            try:
                on_result(futures[f], f.result())
            except Exception as e:
                logger.warning("tagging step failed: %s", e)
                if on_error:
                    on_error(futures[f])


def _fresh(fn):
    """Run fn inside memory.fresh() in the worker thread (the contextvar does not cross threads): a retried batch
    must ask GPT again, not get a cached incomplete reply."""
    def run(*args):
        with memory.fresh():
            return fn(*args)
    return run


def _tags_of(article: dict) -> dict:
    try:
        tags = json.loads(article.get("tags_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return tags if isinstance(tags, dict) else {}


def _labels_of(article: dict) -> set[str]:
    themes = _tags_of(article).get("themes")
    themes = themes if isinstance(themes, dict) else {}
    return {str(themes[k]).strip() for k in ("primary", "secondary", "tertiary") if themes.get(k)}


def _brand_context(project_id: int) -> tuple[str, list[str], str]:
    project = store.get_project(project_id) or {}
    spec = project.get("spec") or {}
    brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or ""
    competitors = [e["name"] for e in spec.get("validated_entities") or [] if e.get("type") == "competitor"]
    context = " ".join(filter(None, [project.get("project_name"), str(spec.get("objective") or "")[:600]]))
    return brand, competitors, context


def _body(article: dict) -> str:
    return batching.trim(article.get("content") or article.get("summary") or "")


def _content_phase(pid: int, prog: _Progress) -> None:
    from . import content
    todo = repo.articles_needing(pid, "content", ALL)
    prog.begin("content", len(todo))

    def save(a, res):
        repo.save_content(a["id"], *res)
        prog.advance()
    _parallel(content.fetch, todo, CONTENT_WORKERS, save)


def _tags_phase(pid: int, llm, prog: _Progress) -> int:
    from ...agents import article_tagging
    brand, competitors, _ = _brand_context(pid)
    todo = repo.articles_needing(pid, "tags", ALL)
    prog.begin("article tags", len(todo))
    batches = batching.pack(todo, _body, out_per_item=article_tagging.OUT_PER_ARTICLE)
    saved = 0

    def save(batch, res):
        nonlocal saved
        for a in batch:
            tags = res.get(a["id"])
            repo.save_tags(a["id"], tags, None if tags is not None else "model returned no tags")
            saved += tags is not None
        prog.advance(len(batch))
    _parallel(_fresh(lambda b: article_tagging.tag(llm, b, brand, competitors)), batches, _workers(), save,
              lambda batch: prog.advance(len(batch)))
    return saved


def _untitled_labels(pid: int) -> bool:
    """True when a tagged article carries a theme label that has no title yet (e.g. a run died before themes)."""
    titles = repo.theme_titles(pid)
    return any(theme_key(l) not in titles for a in repo.all_articles(pid) if a["tag_status"] == "tagged"
               for l in _labels_of(a))


def _themes_phase(pid: int, llm, prog: _Progress) -> None:
    from ..deliverable import theme_synthesis
    counts: Counter = Counter()
    display: dict[str, str] = {}
    heads: dict[str, list[str]] = {}
    for a in repo.all_articles(pid):
        if a["tag_status"] != "tagged":
            continue
        for label in _labels_of(a):
            key = theme_key(label)
            counts[key] += 1
            display.setdefault(key, label)
            if len(heads.setdefault(key, [])) < HEADLINES_PER_LABEL and a["title"]:
                heads[key].append(a["title"][:140])
    prog.begin("themes", 1)
    mapping: dict[str, str] = {}
    if len(counts) >= 2:
        labels = [{"label": display[k], "articles": c, "sample_headlines": heads[k]}
                  for k, c in counts.most_common(theme_synthesis.MAX_THEMES)]
        mapping = theme_synthesis.consolidate_labels(llm, _brand_context(pid)[2], labels)
    # a label GPT left out (or beyond the top 80) keeps its own wording, so it counts as titled on the next run
    repo.save_theme_titles(pid, {**display, **mapping})
    prog.advance()


def _rq_phase(pid: int, llm, prog: _Progress, only_rq: str | None = None) -> None:
    from ...agents import rq_tagging
    from ..deliverable import rows
    from ..strategy import tag_schemas
    schemas = tag_schemas.project_tag_schemas(pid, llm)
    for rq in rows.approved_rqs(pid):
        if only_rq and rq.id != only_rq:
            continue
        schema = schemas.get(rq.id)
        sig = rq_tagging.signature(rq, schema)
        repo.adopt_rematched(pid, rq.id, sig)       # rows a query edit re-matched for free are current
        todo = repo.rq_rows_needing(pid, rq.id, sig, ALL)
        prog.begin(f"{rq.id} tags", len(todo))
        batches = batching.pack(todo, rq_tagging._body, out_per_item=rq_tagging.OUT_PER_ARTICLE)

        def save(batch, res, rq=rq, sig=sig):
            for a in batch:
                result = res.get(a["id"])
                if result is None:      # left untagged: the next run picks it up again
                    continue
                conf = _tags_of(a).get("overall_sentiment_confidence")
                repo.save_rq(a["id"], pid, rq.id, sig, result, rq_tagging.status_for(result, conf))
            prog.advance(len(batch))
        _parallel(_fresh(lambda b, rq=rq, schema=schema: rq_tagging.tag(llm, rq, schema, b)), batches, _workers(),
                  save, lambda batch: prog.advance(len(batch)))


def _relations_phase(pid: int, llm, prog: _Progress) -> None:
    from ..research import relations
    arts = repo.all_articles(pid)
    prog.begin("relations", 1)
    if any(a["tag_status"] == "tagged" and a["syndicated_json"] is None for a in arts):
        items = [{"id": a["id"], "url": a["url"], "title": a["title"], "publication": a["outlet"],
                  "content": a["content"] or a["summary"] or ""} for a in arts]
        found, _method = relations.find_relations(items, llm)
        repo.save_relations(pid, found)
    prog.advance()


def run_job(project_id: int, job_id: str, llm=None, only_rq: str | None = None) -> None:
    from ..usage.service import scope as usage_scope
    with usage_scope(project_id=project_id, stage="dataset_tagging"):
        _run_job(project_id, job_id, llm, only_rq)


def _run_job(project_id: int, job_id: str, llm=None, only_rq: str | None = None) -> None:
    """The job body. A failed phase is logged and the next one still runs; the running flag is always cleared."""
    prog = _Progress(project_id, job_id)
    started = time.time()
    with _LOCK:
        _RUNNING.add(project_id)
    try:
        store.update_job(job_id, status="running", progress_pct=0)
        if llm is None:
            from ...core.llm_provider import get_llm_client
            llm = get_llm_client()
        new_tags = 0

        def match():        # a new upload is mapped to the questions first (free): no match, no GPT
            if repo.tagging_counts(project_id)["unmatched"]:
                from .service import match_rqs
                match_rqs(project_id)

        def tags():
            nonlocal new_tags
            new_tags = _tags_phase(project_id, llm, prog)
            repo.inherit_article_tags(project_id)       # syndicated copies take their original's tags

        def themes():
            if new_tags or _untitled_labels(project_id):          # unchanged tags keep their titles: no GPT call
                _themes_phase(project_id, llm, prog)
        def rq_tags(only=None):
            _rq_phase(project_id, llm, prog, only)
            repo.inherit_rq_rows(project_id)            # ...and their original's research-question results
        steps = (("match", match), ("content", lambda: _content_phase(project_id, prog)), ("article tags", tags),
                 ("themes", themes), ("RQ tags", rq_tags),
                 ("relations", lambda: _relations_phase(project_id, llm, prog)))
        if only_rq:
            steps = (("RQ tags", lambda: rq_tags(only_rq)),)
        for name, step in steps:
            try:
                step()
            except Exception:
                logger.exception("Tagging phase %s failed for project %s", name, project_id)
        store.update_job(job_id, status="completed", progress_pct=100, result=repo.tagging_counts(project_id))
        if not only_rq:         # a full run: the owner reviews and approves the data set next
            from ..deliverable import notify
            notify.notify_dataset_tagged(project_id, started)
    except Exception as e:
        logger.exception("Tagging job failed for project %s", project_id)
        store.update_job(job_id, status="failed", error=str(e)[:500])
    finally:
        with _LOCK:
            _RUNNING.discard(project_id)
            _STATE.pop(project_id, None)
        events.broadcast({"type": "dataset_tagging", "project_id": project_id, "phase": "done", "done": 0,
                          "total": 0, "message": "Tagging finished"})
