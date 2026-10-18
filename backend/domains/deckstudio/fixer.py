"""The deck's repair agent: every open deck check and every brief ask not yet covered gets its own targeted remedy,
applied to the finished deck (spec.json) with the run's saved context (repair_context.json), so photos, logos and
screenshots already found are kept. A remedy either changes the deck or says plainly why it cannot -- a check that
needs data the sample does not hold is reported, never papered over.

Rounds: validate -> repair what is open -> re-render -> validate, up to MAX_ROUNDS, or until nothing changes."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ...core import config
from ..deliverable import visuals
from ..deliverable.citations import CitationRegistry, domain_of
from ..deliverable.engine_insights import _by_headline
from ..deliverable.engine_types import RQ
from ..deliverable.ingest import Article, normalize_url, parse_date
from ..deliverable.insights import draft_section
from . import validate, verbatims, vision
from .spec import DeckSpec, SlideSpec

logger = logging.getLogger(__name__)
MAX_ROUNDS = 3
CONTEXT_FILE = "repair_context.json"
SCOPES = ("checks", "brief", "all")


class Unfixable(Exception):
    """A check the agent cannot repair: the reason is shown to the analyst."""


@dataclass
class Repair:
    spec: DeckSpec
    context: dict
    llm: object
    deck_dir: Path
    log: object = logger.info
    registry: CitationRegistry = field(default=None)
    changed: bool = False
    misleading: set = field(default_factory=set)      # articles that led a card off its category: never reused

    def __post_init__(self):
        if self.registry is None:
            self.registry = CitationRegistry.seeded(self.context.get("citations") or [])

    @property
    def checklist(self) -> list[dict]:
        return self.context.setdefault("checklist", [])


def _article(d: dict) -> Article:
    return Article(url=d["url"], norm_url=normalize_url(d["url"]), title=d.get("title") or "",
                   date=parse_date(d.get("date")), outlet=d.get("outlet") or "", text=d.get("text") or "",
                   sentiment=None, reach=0.0)


def _section_of(slide: SlideSpec, ctx: dict) -> dict | None:
    return (ctx.get("sections") or {}).get(slide.id.rsplit("-", 1)[0])


def _chart_slides(r: Repair) -> list[SlideSpec]:
    return validate._chart_slides(r.spec.slides, [RQ(**q) for q in r.context.get("rqs") or []])


def _key(name) -> str:
    return str(name or "").strip().rstrip(":").lower()          # as engine_insights._by_headline keys a card


def _cite_numbers(slide: SlideSpec) -> None:
    slide.citations = list(dict.fromkeys(n for c in slide.cards for n in c.get("citations") or []))


# ---- remedies: one per check ------------------------------------------------------------------------------------

def _related(slide: SlideSpec, r: Repair) -> set[str]:
    """The categories of the question's other theme-like charts (see validate.off_topic_cards)."""
    if validate._NAMED_THINGS.search(slide.id):
        return set()
    rq = slide.id.split("-", 1)[0]
    return {g.strip().lower() for s in _chart_slides(r) if s.id.split("-", 1)[0] == rq
            and not validate._NAMED_THINGS.search(s.id) for g in validate._segments(s)}


def explain_categories(r: Repair, _row: dict) -> str:
    """Each category of a breakdown chart gets its own card, written from that category's own articles; a category
    no article explains is shown with its count and says so, instead of being silently left out."""
    done = []
    for slide in _chart_slides(r):
        segs = validate._segments(slide)
        have = _by_headline(slide.cards)
        missing = [g for g in segs if _key(g) not in have]
        if not missing:
            continue
        info = _section_of(slide, r.context) or {}
        owned = {normalize_url(a["url"]): [g] for g in missing for a in (info.get("segments") or {}).get(g, [])}
        # a brand study's cards cite sources that name a brand; a territory study's cite the conversation itself
        brand_first = float((r.context.get("validate") or {}).get("brand_share", 1.0)) >= validate.TERRITORY_SHARE
        arts = [a for g in missing for a in (info.get("segments") or {}).get(g, [])
                if normalize_url(a["url"]) not in r.misleading]
        if brand_first:
            arts = sorted(arts, key=lambda a: not a.get("brands"))
        cands = [_article(a) for a in arts]
        cands = list({a.norm_url: a for a in cands}.values())
        found = {}
        if cands and r.llm is not None:
            cards = draft_section(f"{slide.question} - {slide.title}", info.get("facts") or slide.facts_allowed, cands,
                                  r.registry, r.llm, 1, avoid=[f"{c.get('headline')}: {c.get('text')}" for c in slide.cards],
                                  segments=missing, article_segments=owned,
                                  related_segments=_related(slide, r))
            found = {k: v for k, v in _by_headline(cards or []).items() if not v.get("fact_only")}
        chart = slide.charts[0]
        values = dict(zip([str(c) for c in chart.get("categories") or []], chart.get("values") or []))
        unit = "%" if chart.get("unit") == "percent" else " articles"
        for g in missing:
            if _key(g) not in found:            # no article explains it: its count, said plainly
                found[_key(g)] = {"headline": g, "count_only": True, "citations": [],
                                    "text": f"{values.get(g, '')}{unit} in this chart. No sampled article in this "
                                            "category explains what drives it, so it is shown as a count only."}
        cards = {**have, **found}
        summary = [c for c in slide.cards if _key(c.get("headline")) not in {_key(g) for g in segs} and c.get("citations")]
        slide.cards = [cards[_key(g)] for g in segs if _key(g) in cards]
        if summary and not any(c.get("citations") for c in slide.cards):
            slide.cards = summary[:1] + slide.cards       # the slide keeps a cited summary beside its counts
        slide.treatment = "S" if len(slide.cards) > 1 else slide.treatment
        _cite_numbers(slide)
        drafted = sum(1 for g in missing if not found[_key(g)].get("count_only"))
        done.append(f"{slide.id}: {drafted} drafted, {len(missing) - drafted} shown as counts")
    if not done:
        raise Unfixable("every category already has its card")
    r.changed = True
    return "; ".join(done)


def summarise_bare(r: Repair, _row: dict) -> str:
    """A chart slide without a cited summary gets one, drafted from the chart's facts and its candidate sources."""
    fixed, left = [], []
    for slide in _chart_slides(r):
        if validate._cited([slide]):
            continue
        info = _section_of(slide, r.context) or {}
        cands = [_article(a) for a in info.get("candidates") or []]
        cards = draft_section(f"{slide.question} - {slide.title}", info.get("facts") or slide.facts_allowed, cands,
                              r.registry, r.llm, 1) if cands and r.llm is not None else []
        cited = [c for c in cards if c.get("citations")]
        if cited:
            slide.cards = cited[:1] + [c for c in slide.cards if c.get("count_only")]
            _cite_numbers(slide)
            fixed.append(slide.id)
        else:
            left.append(slide.id)
    if not fixed:
        raise Unfixable("no source article supports a summary for " + ", ".join(left[:4]))
    r.changed = True
    return f"summaries drafted for {', '.join(fixed)}" + (f"; none possible for {', '.join(left)}" if left else "")


def _candidates_for(slide: SlideSpec, r: Repair) -> list[dict]:
    info = _section_of(slide, r.context)
    if info:
        return [a for seg in (info.get("segments") or {}).values() for a in seg] + (info.get("candidates") or [])
    q = (r.context.get("questions") or {}).get(slide.id.split("-", 1)[0].upper()) or {}
    return q.get("candidates") or []


def replace_stray_citations(r: Repair, _row: dict) -> str:
    """A card citing a source that never names a brand is redrafted from sources that do (a citation is never
    swapped under a sentence written from another article); with none, the card goes if the slide has others."""
    brands_of = r.context.setdefault("citation_brands", {})
    stray = {n for n in validate._cited(r.spec.slides) if not brands_of.get(n)}
    redrafted, removed, kept = 0, 0, []
    for slide in r.spec.slides:
        bad = [c for c in slide.cards if {str(n) for n in c.get("citations") or []} & stray]
        segs = {_key(g): g for g in validate._segments(slide)}
        info = _section_of(slide, r.context) or {}
        for card in bad:
            seg = segs.get(_key(card.get("headline")))
            if seg:      # a category's card stays about its category: only its own articles that name a brand
                pool = [a for a in (info.get("segments") or {}).get(seg, []) if a.get("brands")
                        and normalize_url(a["url"]) not in r.misleading]
                naming = [_article(a) for a in pool]
                extra = {"segments": [seg], "article_segments": {x.norm_url: [seg] for x in naming},
                         "related_segments": _related(slide, r)}
            else:
                naming = [_article(a) for a in _candidates_for(slide, r) if a.get("brands")]
                extra = {}
            others = [f"{c.get('headline')}: {c.get('text')}" for c in slide.cards if c is not card]
            new = draft_section(f"{slide.question} - {slide.title}", slide.facts_allowed, naming, r.registry, r.llm, 1,
                                avoid=others, **extra) if naming and r.llm is not None else []
            new = [c for c in new if c.get("citations") and not c.get("fact_only")
                   and (not seg or _key(c.get("headline")) == _key(seg))]
            if new:      # the redrafted card keeps its own headline: never a new text under an old category name
                slide.cards[slide.cards.index(card)] = new[0]
                redrafted += 1
            elif seg:    # a category needs its card: kept, and the analyst is told no brand-naming source exists
                kept.append(f"{slide.id} ({seg}: no article in it names a brand)")
            elif len(slide.cards) > 1:
                slide.cards.remove(card)
                removed += 1
            else:
                kept.append(f"{slide.id} (its only card)")
        _cite_numbers(slide)
    if not redrafted and not removed:
        raise Unfixable("no brand-naming source to redraft from: " + ", ".join(kept[:4]))
    r.changed = True
    return f"{redrafted} card(s) redrafted from brand-naming sources, {removed} removed" + \
        (f"; kept as they are: {', '.join(kept)}" if kept else "")


def _logo_folder(r: Repair) -> Path:
    return r.deck_dir.parent / "logos"


def mark_labels(r: Repair, _row: dict) -> str:
    """Every brand, retailer and outlet label gets a mark: a found logo, else its initial in the brand colour."""
    added = []
    for slide in _chart_slides(r):
        if not validate._ENTITY_CHART.search(slide.id):
            continue
        for name in [str(c) for ch in slide.charts for c in ch.get("categories") or []]:
            if name not in slide.logos and (badge := visuals.letter_badge_png(name, _logo_folder(r))):
                slide.logos[name] = str(badge)
                added.append(name)
    if not added:
        raise Unfixable("no label without a mark")
    r.changed = True
    return f"marks added for {', '.join(added[:8])}"


def retry_logos(r: Repair, _row: dict) -> str:
    """Brands still shown as an initial: the logo search runs again (more candidate domains, the vision check)."""
    badged = sorted({str(c) for s in _chart_slides(r) if validate._BRAND_CHART.search(s.id) for ch in s.charts
                     for c in ch.get("categories") or [] if str(c) in s.logos and visuals.is_badge(s.logos[str(c)])})
    if not badged:
        raise Unfixable("no brand shown as an initial")
    category = r.context.get("category") or ""
    judge = (lambda data, name, domain="": vision.is_logo_of(r.llm, data, name, category=category, domain=domain)) \
        if r.llm is not None else None
    found = visuals.logos(badged, _logo_folder(r), judge=judge, hint=category)
    if not found:
        raise Unfixable(f"no verified logo exists for {', '.join(badged[:6])}; their initials stay")
    for s in r.spec.slides:
        s.logos.update({n: str(p) for n, p in found.items() if n in s.logos})
    r.changed = True
    return f"verified logos found for {', '.join(found)}"


def recapture_verbatims(r: Repair, _row: dict) -> str:
    """Posts without a picture are captured again (social photos now load before the shot)."""
    by_url = {v["url"]: v for items in (r.context.get("verbatims_by_rq") or {}).values() for v in items}
    todo = [(s, c) for s in r.spec.slides if s.type == "verbatim_wall" for c in s.cards if not c.get("image")]
    if not todo:
        raise Unfixable("every verbatim has its picture")
    got = verbatims.collect([by_url.get(c.get("url"), {"url": c.get("url"), "outlet": c.get("headline", "")})
                             for _s, c in todo], config.DATA_DIR / "verbatims")
    n = 0
    for (_s, card), g in zip(todo, got):
        if g.get("image"):
            card["image"] = g["image"]
            n += 1
    if not n:
        raise Unfixable(f"{len(todo)} post(s) could not be captured or drawn")
    r.changed = True
    return f"{n} of {len(todo)} verbatim picture(s) captured"


def source_icons(r: Repair, _row: dict) -> str:
    """A cited source without an icon gets its site's icon, else its initial."""
    folder = r.deck_dir.parent / "favicons"
    added = 0
    for n, meta in r.spec.citation_meta.items():
        if meta.get("icon"):
            continue
        icon = visuals.favicon_png(domain_of(meta.get("url") or ""), folder) or \
            visuals.letter_badge_png(meta.get("outlet") or "?", folder)
        if icon:
            meta["icon"] = str(icon)
            added += 1
    if not added:
        raise Unfixable("no icon could be made")
    r.changed = True
    return f"{added} source icon(s) added"


def drop_placeholders(r: Repair, _row: dict) -> str:
    """A chart of only 'Not stated' / 'Unknown' answers nothing: the slide is removed."""
    empty = [s for s in _chart_slides(r) for ch in s.charts[:1]
             if ch.get("categories") and all(str(c).strip().lower() in validate._NO_ANSWER for c in ch["categories"])]
    if not empty:
        raise Unfixable("no placeholder chart")
    r.spec.slides = [s for s in r.spec.slides if s not in empty]
    r.changed = True
    return "removed " + ", ".join(s.id for s in empty)


def redraft_off_topic(r: Repair, row: dict) -> str:
    """Cards that write about something other than their category are removed and redrafted from that
    category's own articles."""
    off = validate.off_topic_cards(_chart_slides(r))
    if not off:
        raise Unfixable("every category card is about its category")
    bad = {(sid, _key(h)) for sid, h in off}
    urls = {str(e["n"]): e["url"] for e in r.registry.entries()}
    for slide in _chart_slides(r):
        for c in slide.cards:
            if (slide.id, _key(c.get("headline"))) in bad:
                r.misleading |= {normalize_url(urls[str(n)]) for n in c.get("citations") or [] if str(n) in urls}
        slide.cards = [c for c in slide.cards if (slide.id, _key(c.get("headline"))) not in bad]
    return f"{len(off)} card(s) removed; " + explain_categories(r, row)


REMEDIES = (
    ("Each category card explains its own category", redraft_off_topic),
    ("Every chart category has its own insight", explain_categories),
    ("Every chart slide has a cited summary", summarise_bare),
    ("Citations name the brand or a competitor literally", replace_stray_citations),
    ("Every brand, retailer and outlet in a chart shows its logo", mark_labels),
    ("Brand logos are verified", retry_logos),
    ("Verbatims show the post or article screenshot", recapture_verbatims),
    ("Citations show their source icon", source_icons),
    ("No chart shows only", drop_placeholders),
)


def _brands_by_url(ctx: dict) -> dict[str, list[str]]:
    arts = [a for sec in (ctx.get("sections") or {}).values()
            for a in [x for seg in (sec.get("segments") or {}).values() for x in seg] + (sec.get("candidates") or [])]
    arts += [a for q in (ctx.get("questions") or {}).values() for a in q.get("candidates") or []]
    return {normalize_url(a["url"]): a.get("brands") or [] for a in arts}


def sync_sources(r: Repair) -> None:
    """Sources new to the deck are listed (with their icon, and the brands they name) like the ones the run cited."""
    known = set(r.spec.citation_meta)
    named = _brands_by_url(r.context)
    for e in r.registry.entries():
        n = str(e["n"])
        if n in known:
            continue
        r.context.setdefault("citation_brands", {})[n] = named.get(normalize_url(e["url"]), [])
        icon = visuals.favicon_png(domain_of(e["url"]), r.deck_dir.parent / "favicons")
        r.spec.citation_meta[n] = {"outlet": e.get("outlet") or domain_of(e["url"]), "icon": str(icon or ""),
                                   "url": e["url"] if e["url"].startswith(("http://", "https://")) else ""}
        r.context.setdefault("citations", []).append(e)
        pages = [s for s in r.spec.slides if s.type == "citations"]
        if pages and pages[-1].tables:
            pages[-1].tables[0]["rows"].append([n, e.get("outlet") or domain_of(e["url"]), e.get("title") or "",
                                                verbatims.us_date(e.get("date") or "")])
            pages[-1].facts_allowed += [n, e.get("date") or "", verbatims.us_date(e.get("date") or "")]


# ---- the brief: asks the keyword checklist could not place --------------------------------------------------------

_JSON = re.compile(r"\{.*\}", re.S)
# slides that report on the deck rather than answer the brief: never accepted as where an ask is answered
_NOT_ANSWERS = ("cover", "closing", "citations", "scorecard", "checklist", "methodology")


def recheck_brief(r: Repair) -> list[str]:
    """An agent reads the deck's slide titles and summaries and says, for each brief ask still open, where the deck
    answers it. An ask moves to covered only when the slide it names exists; otherwise its gap stays, with why."""
    gaps = [row for row in r.checklist if row.get("status") != "covered"]
    # a question the automatic check found unanswered for a concrete reason (an analysis the data cannot fill) is
    # not re-judged from slide titles: the reason is reported, and only the data can close it
    data_gaps = [f"Brief: {row['ask'][:60]} - needs data: {str(row.get('note'))[:140]}"
                 for row in gaps if row.get("kind") == "question"]
    open_rows = [row for row in gaps if row.get("kind") != "question"]
    if not open_rows:
        return data_gaps
    if r.llm is None:
        return [f"Brief: {row['ask'][:60]} - no agent available to re-check" for row in open_rows]
    catalog = [{"slide": i, "id": s.id, "title": s.title, "kicker": s.kicker,
                "cards": [f"{c.get('headline', '')}: {str(c.get('text', ''))[:220]}" for c in s.cards][:5],
                **({"table_header": s.tables[0].get("header")} if s.tables else {})}
               for i, s in enumerate(r.spec.slides, start=1) if s.type not in _NOT_ANSWERS]
    shown = {c["slide"] for c in catalog}
    prompt = ("A client brief asked for the items below; an automatic check marked each one not fully answered, for "
              "the reason given. Using only the deck's slides listed, say for each item whether a slide really "
              "delivers it. A title is not enough: the slide's cards or table must contain the answer itself (for "
              "'themes for each competitor', themes broken down competitor by competitor, not themes overall). "
              "When covered, copy 6-15 consecutive words from that slide's cards or table header as evidence.\n"
              f"ITEMS: {json.dumps([{'ask': row['ask'], 'reason': row.get('note', '')} for row in open_rows])}\n"
              f"SLIDES: {json.dumps(catalog)}\n"
              'Return JSON {"items": [{"ask": "...", "covered": true|false, "slide": <slide number or null>, '
              '"evidence": "<words copied from the slide>", "why": "one short sentence"}]}')
    try:
        reply = json.loads(_JSON.search(r.llm.chat([{"role": "user", "content": prompt}], format_json=True)).group(0))
    except Exception as e:      # no verdict: the gaps stay as they are
        return [f"Brief re-check unavailable: {type(e).__name__}"]
    verdicts = {str(v.get("ask")): v for v in reply.get("items") or [] if isinstance(v, dict)}
    out, moved = [], False
    for row in open_rows:
        v = verdicts.get(row["ask"]) or {}
        slide = v.get("slide")
        if v.get("covered") and slide in shown and _evidence_on(r.spec.slides[slide - 1], str(v.get("evidence") or "")):
            row.update(status="covered", note=f"slide {slide}: {str(v.get('why') or '')[:120]}")
            out.append(f"Brief: {row['ask'][:60]} - covered on slide {slide}")
            moved = r.changed = True
        else:
            out.append(f"Brief: {row['ask'][:60]} - still {row['status']}: {str(v.get('why') or row.get('note'))[:120]}")
    if moved:
        refresh_brief_slides(r.spec, r.checklist)
    return out + data_gaps


EVIDENCE_WORDS = 6


def _plain_words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _evidence_on(slide: SlideSpec, evidence: str) -> bool:
    """The agent's quote is really on the slide (its cards or table header), and long enough to mean something."""
    quote = _plain_words(evidence)
    if len(quote.split()) < EVIDENCE_WORDS:
        return False
    body = _plain_words(" ".join([f"{c.get('headline', '')} {c.get('text', '')}" for c in slide.cards]
                                 + [" ".join(map(str, t.get("header") or [])) for t in slide.tables]))
    return quote in body


def refresh_brief_slides(spec: DeckSpec, rows: list[dict]) -> None:
    counts = {k: sum(1 for x in rows if x["status"] == k) for k in ("covered", "partial", "missing")}
    for s in spec.slides:
        if s.type == "scorecard":
            s.cards = [{"headline": str(counts[k]), "text": k} for k in ("covered", "partial", "missing")]
            s.tables = [{**(s.tables[0] if s.tables else {}), "header": ["Brief asked", "Status", "Why"],
                         "rows": [[g["ask"], g["status"], g["note"]] for g in rows if g["status"] != "covered"]}]
            s.facts_allowed += [str(v) for v in counts.values()]
    by_ask = {x["ask"]: x for x in rows}
    for s in spec.slides:
        if s.type == "checklist" and s.tables:
            s.tables[0]["rows"] = [[row[0], by_ask[row[0]]["status"], row[2], by_ask[row[0]]["note"]]
                                   if row and row[0] in by_ask else row for row in s.tables[0]["rows"]]


# ---- the loop -----------------------------------------------------------------------------------------------------

def repair_round(r: Repair, checks: list[dict], scope: str = "all") -> list[str]:
    """One pass over the open checks; returns what was done or why not, one line each."""
    lines = []
    if scope in ("checks", "all"):
        for row in [c for c in checks if c["status"] != "pass" and not c["check"].startswith("Brief: ")]:
            remedy = next((fn for prefix, fn in REMEDIES if row["check"].startswith(prefix)), None)
            if remedy is None:
                lines.append(f"{row['check'][:70]}: no automatic repair - {row['detail'][:120]}")
                continue
            try:
                lines.append(f"Repaired - {row['check'][:70]}: {remedy(r, row)}")
                sync_sources(r)            # sources a remedy just cited are known (brands, icon) to the next one
            except Unfixable as e:
                lines.append(f"Could not repair - {row['check'][:70]}: {e}")
            except Exception as e:      # one remedy failing never stops the others
                logger.exception("repair %s failed", row["check"])
                lines.append(f"Could not repair - {row['check'][:70]}: {type(e).__name__}")
        sync_sources(r)
    if scope in ("brief", "all"):
        lines += recheck_brief(r)
    return lines


def load(deck_dir: Path) -> tuple[DeckSpec, dict]:
    spec = DeckSpec.from_dict(json.loads((deck_dir / "spec.json").read_text(encoding="utf-8")))
    path = deck_dir / CONTEXT_FILE
    return spec, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})


REPLACE_ATTEMPTS = 6
REPLACE_WAIT_S = 0.25


def _write(path: Path, data) -> None:
    """Written whole or not at all: a crash mid-write never leaves a half spec behind."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            tmp.replace(path)
            return
        except PermissionError:     # Windows: a reader or the virus scanner holds the target for a moment
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_S * (attempt + 1))


def save(r: Repair) -> None:
    _write(r.deck_dir / "spec.json", r.spec.to_dict())
    _write(r.deck_dir / CONTEXT_FILE, r.context)


def validate_with(r: Repair, pptx: Path | None) -> list[dict]:
    v = r.context.get("validate") or {}
    return validate.validate_deck(r.spec, [RQ(**q) for q in r.context.get("rqs") or []], r.checklist,
                                  v.get("brand_products") or [], has_competitors=bool(v.get("has_competitors")),
                                  citation_brands=r.context.get("citation_brands") or None, pptx=pptx,
                                  is_category=bool(v.get("is_category")), mixed_media=bool(v.get("mixed_media")),
                                  brand_share=float(v.get("brand_share", 1.0)))


def _open(checks: list[dict], checklist: list[dict], scope: str) -> bool:
    deck_open = any(c["status"] != "pass" and not c["check"].startswith("Brief: ") for c in checks)
    # a question gap with a data reason is reported once, not re-tried: only re-checkable asks keep a round going
    brief_open = any(x.get("status") != "covered" and x.get("kind") != "question" for x in checklist)
    return {"checks": deck_open, "brief": brief_open}.get(scope, deck_open or brief_open)


def rebuild(spec: DeckSpec, deck_dir: Path, on_fix=None) -> dict:
    """The repaired deck rendered (with the layout repair pass), its assets inlined, and exported again."""
    from . import creative, exporter, indexer, renderer
    html, report = creative.compose(spec, deck_dir, None, indexer.reference_text_shingles(), on_fix=on_fix)
    renderer.inline_assets(html)
    return {**exporter.export_all(html, spec, deck_dir, spec.title), "html": html, "report": report}


def run_repairs(r: Repair, checks: list[dict], scope: str = "all", on_fix=None) -> tuple[list[dict], dict | None]:
    """Repair rounds until every check passes, nothing more can change, or MAX_ROUNDS; returns the final checks
    and the last export (None when the deck did not change)."""
    out = None
    if not _open(checks, r.checklist, scope):
        r.log(f"Repair agent: nothing it can repair in {'the brief' if scope == 'brief' else 'the deck checks'}")
        if scope in ("brief", "all"):
            for line in recheck_brief(r):          # the data gaps, each with its reason
                r.log(line)
    for k in range(1, MAX_ROUNDS + 1):
        if not _open(checks, r.checklist, scope):
            break
        r.changed = False
        r.log(f"Repair agent, round {k}: {sum(c['status'] != 'pass' for c in checks)} open check(s)")
        for line in repair_round(r, checks, scope):
            r.log(line)
        if not r.changed:
            r.log("Repair agent: nothing more can be changed automatically")
            break
        out = rebuild(r.spec, r.deck_dir, on_fix)
        checks = validate_with(r, out["pptx"])
        r.log(f"Re-check after round {k}: {sum(c['status'] == 'pass' for c in checks)} of {len(checks)} checks pass")
    save(r)
    for c in checks:
        if c["status"] != "pass":
            r.log(f"Still open - {c['check'][:80]}: {c['detail'][:140]}")
    return checks, out
