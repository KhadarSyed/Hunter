"""Analysis plan: the LLM picks modules from a fixed catalog per RQ; it never supplies numbers."""
from __future__ import annotations

import json
import logging
import re

from ...agents import question_dimensions as qd
from .engine_types import RQ, EngineRow

logger = logging.getLogger(__name__)

MODULES: dict[str, dict] = {
    "share_kpi": {"needs_extraction": False, "desc": "share of coverage for this question (KPI tile)"},
    "volume_trend": {"needs_extraction": False, "desc": "monthly volume line with the top-5 peaks labelled"},
    "sentiment_split": {"needs_extraction": False, "desc": "positive / neutral / negative split (doughnut)"},
    "outlet_ranking": {"needs_extraction": False, "desc": "top outlets by articles (bar chart)"},
    "reach": {"needs_extraction": False, "desc": "total and top-outlet reach (bar chart)"},
    "theme_clusters": {"needs_extraction": False, "desc": "top themes from enrichment (treemap)"},
    "entities": {"needs_extraction": True, "desc": "named experts / celebrities / brands / products / retailers (table + chart)"},
    "brand_sov": {"needs_extraction": False, "desc": "brand share of voice with logos (bar chart)"},
    "top_articles": {"needs_extraction": False, "desc": "most-read articles (table)"},
}
ENTITY_KINDS = ("experts", "celebrities", "brands", "products", "retailers")
MAX_MODULES = 6
_ENTITY_HINTS = (("expert", "experts"), ("dermatolog", "experts"), ("pediatric", "experts"), ("hcp", "experts"),
                 ("celebrit", "celebrities"), ("influencer", "celebrities"), ("retailer", "retailers"),
                 ("deal", "retailers"), ("product", "products"))


def validate_plan(plan: dict, rq_id: str) -> dict | None:
    if not isinstance(plan, dict) or not isinstance(plan.get("modules"), list):
        return None
    modules = []
    for m in plan["modules"]:
        if not isinstance(m, dict) or m.get("module") not in MODULES:
            continue
        kind = m.get("entity_kind")
        if m["module"] == "entities" and kind not in ENTITY_KINDS:
            continue
        modules.append({"module": m["module"], "title": str(m.get("title") or m["module"]).strip()[:80],
                        "entity_kind": kind if m["module"] == "entities" else None})
    if not modules:
        return None
    if modules[0]["module"] != "share_kpi":
        modules = [{"module": "share_kpi", "title": "Share of coverage", "entity_kind": None}] + \
                  [m for m in modules if m["module"] != "share_kpi"]
    return {"rq_id": rq_id, "title": str(plan.get("title") or rq_id).strip()[:90], "modules": modules[:MAX_MODULES]}


def default_plan(rq: RQ, rows: list[EngineRow]) -> dict:
    text = rq.question.lower()
    modules = [{"module": "share_kpi", "title": "Share of coverage", "entity_kind": None}]
    if any(r.article.date for r in rows):
        modules.append({"module": "volume_trend", "title": "Coverage over time", "entity_kind": None})
    kind = next((k for hint, k in _ENTITY_HINTS if hint in text), None)
    if kind:
        modules.append({"module": "entities", "title": f"Named {kind}", "entity_kind": kind})
    if any(w in text for w in ("brand", "competitor", "share of voice")):
        modules.append({"module": "brand_sov", "title": "Brand share of voice", "entity_kind": None})
    modules += [{"module": "outlet_ranking", "title": "Top outlets", "entity_kind": None},
                {"module": "sentiment_split", "title": "Sentiment", "entity_kind": None},
                {"module": "top_articles", "title": "Most-read articles", "entity_kind": None}]
    return {"rq_id": rq.id, "title": rq.question[:90] or rq.id, "modules": modules[:MAX_MODULES]}


def _profile(rows: list[EngineRow]) -> dict:
    return {"articles": len(rows), "dated": sum(1 for r in rows if r.article.date),
            "with_sentiment": sum(1 for r in rows if r.article.sentiment),
            "with_reach": sum(1 for r in rows if r.article.reach),
            "outlets": len({r.article.outlet for r in rows if r.article.outlet}),
            "brands_mentioned": sum(1 for r in rows if (r.entities or {}).get("brands"))}


def plan_rq(llm, rq: RQ, rows: list[EngineRow]) -> tuple[dict, str]:
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return default_plan(rq, rows), "default"
    messages = [
        {"role": "system", "content": "You plan the analysis slides for one research question of a media-research "
         "deck. Choose 3-6 modules from CATALOG that best answer the question, in presentation order, starting with "
         "share_kpi. For 'entities' set entity_kind to one of " + ", ".join(ENTITY_KINDS) + ". Never include numbers. "
         "Return JSON only: {\"title\": \"<slide title, max 8 words>\", \"modules\": [{\"module\": \"<catalog key>\", "
         "\"title\": \"<chart title>\", \"entity_kind\": null}]}"},
        {"role": "user", "content": f"QUESTION: {rq.question}\nDATA PROFILE: {json.dumps(_profile(rows))}\n"
         f"CATALOG: {json.dumps({k: v['desc'] for k, v in MODULES.items()})}"},
    ]
    try:
        plan = validate_plan(json.loads(llm.chat(messages, format_json=True)), rq.id)
    except (json.JSONDecodeError, TypeError, RuntimeError) as e:
        logger.warning("plan for %s failed (%s); using default plan", rq.id, e)
        plan = None
    if plan is None:
        return default_plan(rq, rows), "default"
    return _ensure_required(plan, rq, rows), "llm"


def _ensure_required(plan: dict, rq: RQ, rows: list[EngineRow]) -> dict:
    """Every RQ with dated articles gets a trend (spec: per-RQ trend with top-5 peaks), and a question about
    experts / celebrities / retailers gets its entity module even when the LLM left it out."""
    modules = [m for m in plan["modules"] if m["module"] != "volume_trend" or any(r.article.date for r in rows)]
    if any(r.article.date for r in rows) and not any(m["module"] == "volume_trend" for m in modules):
        modules.insert(1, {"module": "volume_trend", "title": "Coverage over time", "entity_kind": None})
    kind = next((k for hint, k in _ENTITY_HINTS if hint in rq.question.lower()), None)
    if kind and not any(m["module"] == "entities" and m["entity_kind"] == kind for m in modules):
        modules.insert(2, {"module": "entities", "title": f"Named {kind}", "entity_kind": kind})
    return {**plan, "modules": modules[:MAX_MODULES]}


BREAKDOWN_MODULES = ("question_breakdown", "dimension_crosstab")
MAX_BREAKDOWNS = 2


def _rows_dimension(question: str, dims: list[qd.Dimension]) -> qd.Dimension:
    """The dimension a question breaks the other down by: the one named after "by" ("injury types by sport")."""
    after = question.lower().rsplit(" by ", 1)[1] if " by " in question.lower() else ""
    for d in dims:
        words = [w for w in re.findall(r"[a-z0-9]+", d.label.lower()) if len(w) > 2]
        words += [t.rstrip("*").lower() for v in d.values for t in v.terms] + [v.name.lower() for v in d.values]
        if after and any(re.search(r"(?<![a-z0-9])" + re.escape(w), after) for w in words if w):
            return d
    return dims[0]


def with_breakdowns(plan: dict, rq: RQ, dims: list[qd.Dimension]) -> dict:
    """The question's own dimensions answer it first: one chart per dimension straight after the KPI, and the
    cross-tab when it asks for two ("injury types by sport")."""
    if not dims:
        return plan
    dims = dims[:MAX_BREAKDOWNS]
    kept = [m for m in plan["modules"] if m["module"] not in BREAKDOWN_MODULES]
    added = [{"module": "question_breakdown", "title": d.label, "entity_kind": None, "dimension": qd.to_json([d])[0]}
             for d in dims]
    if len(dims) == 2:
        rows_dim = _rows_dimension(rq.question, dims)
        col_dim = dims[1] if rows_dim is dims[0] else dims[0]
        added.append({"module": "dimension_crosstab", "title": f"{col_dim.label} by {rows_dim.label}",
                      "entity_kind": None, "dimensions": qd.to_json([rows_dim, col_dim])})
    return {**plan, "modules": (kept[:1] + added + kept[1:])[:MAX_MODULES + len(added)]}
