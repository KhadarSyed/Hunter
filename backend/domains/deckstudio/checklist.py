"""'Did we answer the brief?': every research question, expected analysis and requested deliverable, marked
covered / partial / missing with the slides that answer it and a reason when something is short."""
from __future__ import annotations

import re

from ...core import store
from ..deliverable.engine_types import RQ, Section
from .spec import DeckSpec

ASK_MODULES = [
    (r"theme|topic", {"theme_clusters"}), (r"expert", {"entities:experts"}), (r"affiliat", {"entities:experts"}),
    (r"celebrit", {"entities:celebrities"}), (r"brand|share of voice|competit|benchmark", {"brand_sov", "brand_sentiment", "entities:brands"}),
    (r"sentiment|tone", {"sentiment_split", "brand_sentiment"}), (r"outlet|publication", {"outlet_ranking"}),
    (r"trend|over time|month|volume|spike|peak|driver|event|moment", {"volume_trend"}),
    (r"reach|audience", {"reach"}),
    (r"retailer", {"entities:retailers"}),
    (r"social|editorial|source split|media type", {"media_split"}),
    (r"\bby (sport|activit|injur|type|categor|product|occasion)|which (sport|activit|injur|product)",
     {"question_breakdown", "dimension_crosstab"}),
]
DELIVERED = re.compile(r"written summary|executive summary|report|deck|presentation|visual|chart|graph|"
                       r"quantitative|findings", re.I)
NOT_STATED = re.compile(r"not stated", re.I)
DATA_EXPORT = re.compile(r"excel|csv|spreadsheet|data tables?|raw data|data set|dataset|xlsx", re.I)


def brief_asks(project_id: int) -> list[tuple[str, str]]:
    spec = (store.get_latest_spec(project_id) or {}).get("spec") or {}
    scope = (spec.get("source_spec") or {}).get("included_scope") or {}
    return [("analysis", a) for a in scope.get("expected_analyses") or []] + \
           [("deliverable", d) for d in scope.get("deliverables") or []]


def _keys(section: Section) -> set[str]:
    if section.module == "entities":
        return {"entities", f"entities:{section.id.rsplit('-', 1)[-1]}"}
    return {section.module}


def _question_row(rq: RQ, sections: list[Section]) -> dict:
    kpi = next((s for s in sections if s.module == "share_kpi"), None)
    row = {"ask": rq.question, "kind": "question", "rq_id": rq.id, "slides": [], "modules": [s.id for s in sections]}
    if kpi is None or kpi.skipped:
        return {**row, "status": "missing", "note": (kpi.skipped if kpi else "") or "No articles for this question"}
    # an empty extra chart (experts on a parenting-advice question) does not short a question; one it asks for does
    skipped = [s for s in sections if s.skipped and s.module != "share_kpi" and _asked(rq.question, s)
               and not _answered_elsewhere(s, sections)]
    # "affiliation not stated" only falls short of a question that asked about affiliation and has no tag answering it
    asks_affiliation = bool(re.search("affiliat", rq.question.lower()))
    unstated = next((f for s in sections for f in s.facts if NOT_STATED.search(f)), "") \
        if asks_affiliation and not _tag_answers(sections, "affiliat") else ""
    if skipped or unstated:
        return {**row, "status": "partial", "note": unstated or "; ".join(f"{s.title}: {s.skipped}" for s in skipped)}
    return {**row, "status": "covered", "note": ""}


def _answered_elsewhere(empty: Section, sections: list[Section]) -> bool:
    """An empty chart whose subject another drawn chart of the question shows (an empty 'Theme' breakdown beside
    the theme treemap): the question is answered, by the other chart."""
    wanted = set().union(*[mods for pattern, mods in ASK_MODULES if re.search(pattern, empty.title.lower())])
    return bool(wanted) and any(not s.skipped and (s.chart or s.table) and _keys(s) & wanted for s in sections)


def _stems(text: str) -> set[str]:
    """Word stems for matching an ask to an analysis: 'types' and 'type', 'sports' and 'sport' are one stem."""
    words = (w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w
             for w in re.findall(r"[a-z]+", text.lower()))
    return {w[:6] for w in words if len(w) > 3}


MIN_SHARED_STEMS = 2


def _by_title(ask: str, sections: list[Section]) -> list[Section]:
    """Drawn analyses whose title words the ask names ('percent breakdown of injury types per focus sport' ->
    'Injury Type by Sport'): the request is answered even when no analysis keyword in it matched."""
    want = _stems(ask)
    return [s for s in sections if not s.skipped and (s.chart or s.table)
            and len((title := _stems(s.title) - _GENERIC_TITLE) & want) >= min(MIN_SHARED_STEMS, len(title))
            and title and title <= want]


def _asked(question: str, section: Section) -> bool:
    """Did the question ask for what this section shows (by the analysis it names, or its words in the title)?"""
    low = question.lower()
    if _keys(section) & set().union(*[mods for pattern, mods in ASK_MODULES if re.search(pattern, low)]):
        return True
    title = _stems(section.title) - _GENERIC_TITLE
    return bool(title) and title <= _stems(low)


_GENERIC_TITLE = {"share", "covera", "articl", "chart", "breakd", "over", "time", "tagged"}


def _tag_answers(sections: list[Section], word: str) -> Section | None:
    """The question's own tag section for `word` (e.g. 'affiliat') when it was measured: Yes/No counts are an
    answer, even when the answer is 'No'."""
    return next((s for s in sections if s.module == "tag_share" and not s.skipped and word in s.id), None)


def _ask_row(kind: str, ask: str, sections: list[Section], has_brief_doc: bool, has_data_export: bool = False) -> dict:
    low = ask.lower()
    row = {"ask": ask, "kind": kind, "rq_id": None, "slides": [], "modules": []}
    if DATA_EXPORT.search(low) and has_data_export:
        return {**row, "status": "covered", "note": "Delivered as the Excel workbook of data tables"}
    tagged = _tag_answers(sections, "affiliat") if "affiliat" in low else None
    if tagged:
        return {**row, "status": "covered", "note": tagged.facts[0].split(": ", 1)[-1] if tagged.facts else "",
                "modules": [tagged.id]}
    wanted = set().union(*[mods for pattern, mods in ASK_MODULES if re.search(pattern, low)])
    if not wanted:
        # the deck itself delivers these (its charts, its executive summary), however the brief filed the ask
        if DELIVERED.search(low) and (has_brief_doc or "summary" not in low):
            return {**row, "status": "covered", "note": "Delivered as this deck and the Word brief"}
        matched = _by_title(ask, sections)
        if matched:
            return {**row, "status": "covered", "note": f"Answered by: {matched[0].title}",
                    "modules": [m.id for m in matched]}
        return {**row, "status": "missing", "note": "No analysis in this run matches this request"}
    drawn = [s for s in sections if not s.skipped and _keys(s) & wanted]
    if not drawn:
        return {**row, "status": "missing", "note": "The data has no field for this, so no matching analysis could run"}
    unstated = next((f for s in drawn for f in s.facts if NOT_STATED.search(f)), "")
    partial = bool(re.search("affiliat", low) and unstated)
    return {**row, "status": "partial" if partial else "covered", "note": unstated if partial else "",
            "modules": [s.id for s in drawn]}


def build_checklist(rqs: list[RQ], sections_by_rq: dict[str, list[Section]], asks: list[tuple[str, str]],
                    has_brief_doc: bool = True, has_data_export: bool = False) -> list[dict]:
    every = [s for secs in sections_by_rq.values() for s in secs]
    return [_question_row(rq, sections_by_rq.get(rq.id, [])) for rq in rqs] + \
           [_ask_row(kind, ask, every, has_brief_doc, has_data_export) for kind, ask in asks]


def attach_slide_numbers(spec: DeckSpec, rows: list[dict]) -> list[dict]:
    """Slide numbers from the final deck order, written into the checklist slides' tables."""
    order = {s.id: n for n, s in enumerate(spec.slides, start=1)}
    out = []
    for r in rows:
        if r["rq_id"]:
            prefix = r["rq_id"].lower() + "-"
            slides = [n for sid, n in order.items() if sid.startswith(prefix)]
        else:
            slides = [n for sid, n in order.items() for m in r["modules"] if sid.startswith(m + "-")]
        out.append({**r, "slides": sorted(set(slides))})
    pages = [s for s in spec.slides if s.type == "checklist"]
    per = max(1, -(-len(out) // max(1, len(pages))))
    for i, slide in enumerate(pages):
        chunk = out[i * per:(i + 1) * per]
        slide.tables[0]["rows"] = [[r["ask"], r["status"], ", ".join(map(str, r["slides"])) or "—", r["note"]] for r in chunk]
        slide.facts_allowed = slide.facts_allowed + [str(n) for r in chunk for n in r["slides"]]
    return out
