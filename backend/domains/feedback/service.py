"""Learning from analysts: every correction of the AI's tags is kept with the article's embedding, and tagging in the
same organization is shown the closest past corrections as examples to follow.

Kinds:  edit      sentiment / themes / brands changed by an analyst (before and after kept), with an optional comment
        reject    an article rejected for a research question, with the analyst's reason
        relevant  an Irrelevant article an analyst marked relevant for a question
        keep      an article the exclusion list blocked (by keyword) that an analyst kept, with their comment
Article tagging is shown edits; research-question tagging is shown rejects, relevant and keep.

Scope: the organization (a correction in one project guides every project of the same organization, never another
organization's). Rows are recorded in the background and never fail or slow a request; without an embedding provider
nothing is recalled and the prompts are unchanged."""
from __future__ import annotations

import json
import logging

from ...core import store

logger = logging.getLogger(__name__)

ARTICLE_KINDS = ("edit",)
RQ_KINDS = ("reject", "relevant", "keep")
# Article-to-article cosine (title + opening, NVIDIA embed). Measured 2026-11-13 on the synthetic project (log
# 2026-11-13-19): same kind of story 0.68-0.70 (solar vs EV chargers, expansion vs new slots / hiring), different
# stories 0.39-0.53. shortcut: 0.62 rests on 10 pairs; re-measure on a real project's corrections.
MIN_SIMILAR = 0.62
PER_ARTICLE = 2         # closest corrections looked up per article in a batch
MAX_EXAMPLES = 6        # corrections shown per tagging call
MAX_RECORD = 200        # corrections recorded per request (a bulk decision of thousands keeps the first 200)
EMBED_BATCH = 50


def _org(project_id: int) -> int | None:
    from ..exclusions.service import org_of_project
    return org_of_project(project_id)


def _text(article: dict) -> str:
    from ..research.relations import _embed_text
    return _embed_text({"title": article.get("title"), "content": article.get("content") or article.get("summary")})


def _embed(texts: list[str]):
    """(model, list of vectors) or (model, None) when no embedding provider works."""
    from ...core.llm_provider import get_llm_client
    from ...core.nvidia_embed_client import embed_model_name
    model, llm = embed_model_name(), get_llm_client()
    if not model or llm is None or not texts:
        return model, None
    out = []
    for start in range(0, len(texts), EMBED_BATCH):
        out += [list(map(float, v)) for v in llm.embed_batch(texts[start:start + EMBED_BATCH])]
    return model, out if len(out) == len(texts) else None


def record(project_id: int, items: list[dict], by: str | None) -> None:
    """Queue corrections to save. items: {"article_id", "kind", "rq_id"?, "question"?, "before"?, "after"?,
    "comment"?}. Never raises."""
    items = [i for i in items if i.get("article_id")][:MAX_RECORD]
    if not items:
        return
    try:
        from ...core.jobs import runner
        runner.submit(_save, project_id, items, by, name=f"tag_feedback_{project_id}")
    except Exception as e:
        logger.warning("analyst feedback not queued: %s", type(e).__name__)


def _save(project_id: int, items: list[dict], by: str | None) -> int:
    try:
        from ..dataset import repository as dataset_repo
        arts = dataset_repo.articles_by_ids(project_id, [i["article_id"] for i in items])
        items = [i for i in items if i["article_id"] in arts]
        texts = [_text(arts[i["article_id"]]) for i in items]
        try:
            model, vectors = _embed(texts)
        except Exception as e:      # saved without a vector: kept for the record, not recalled
            logger.warning("analyst feedback not embedded: %s", type(e).__name__)
            model, vectors = None, None
        org = _org(project_id)
        dump = lambda v: json.dumps(v, default=str) if v is not None else None  # noqa: E731
        return store.save_feedback([{
            "org_id": org, "source_project_id": project_id, "article_id": i["article_id"], "rq_id": i.get("rq_id"),
            "question": i.get("question"), "kind": i["kind"], "before_json": dump(i.get("before")),
            "after_json": dump(i.get("after")), "comment": (i.get("comment") or "")[:1000] or None,
            "article_text": t, "embedding": vectors[n] if vectors else None, "model": model if vectors else None,
            "created_by": by} for n, (i, t) in enumerate(zip(items, texts))])
    except Exception as e:
        logger.warning("analyst feedback not saved: %s", type(e).__name__)
        return 0


def _fmt_tags(v: dict | None) -> str:
    v = v or {}
    parts = [f"sentiment {v['sentiment']}" if v.get("sentiment") else "",
             f"themes {', '.join(v['themes'])}" if v.get("themes") else "",
             f"brands {', '.join(v['brands'])}" if v.get("brands") else ""]
    return "; ".join(p for p in parts if p) or "(none)"


def _line(f: dict) -> str:
    title = f["article_text"].split("\n", 1)[0][:140]
    q = f'"{f["question"]}"' if f.get("question") else "the research question"
    load = lambda s: json.loads(s) if s else None  # noqa: E731
    what = {
        "edit": lambda: f"AI tags {_fmt_tags(load(f['before_json']))} -> analyst set {_fmt_tags(load(f['after_json']))}",
        "reject": lambda: f"analysts judged it NOT relevant to {q}",
        "relevant": lambda: f"analysts judged it relevant to {q} although the AI / query left it out",
        "keep": lambda: "analysts kept it relevant although a blocked keyword appears in it",
    }[f["kind"]]()
    why = f' Analyst comment: "{f["comment"]}"' if f.get("comment") else ""
    return f'- "{title}" (similarity {f["score"]:.2f}): {what}.{why}'


def guidance(project_id: int, articles: list[dict], kinds: tuple[str, ...]) -> str:
    """A prompt section with the organization's past corrections closest to these articles, or '' (nothing similar,
    nothing recorded, or no embeddings). Never raises."""
    try:
        org = _org(project_id)
        if not articles or not store.count_feedback(org, kinds):
            return ""
        model, vectors = _embed([_text(a) for a in articles])
        if not vectors:
            return ""
        found: dict[int, dict] = {}
        for v in vectors:
            for f in store.nearest_feedback(org, kinds, v, model, PER_ARTICLE):
                if f["score"] >= MIN_SIMILAR and f["score"] > found.get(f["id"], {}).get("score", -1):
                    found[f["id"]] = f
        best = sorted(found.values(), key=lambda f: -f["score"])[:MAX_EXAMPLES]
        if not best:
            return ""
        return ("ANALYST CORRECTIONS ON SIMILAR ARTICLES (this organization's analysts corrected the AI on articles "
                "like these; when an article below is of the same nature, follow the same judgment. Never copy facts "
                "or names from these examples into another article):\n" + "\n".join(map(_line, best)))
    except Exception as e:
        logger.warning("analyst feedback not recalled: %s", type(e).__name__)
        return ""
