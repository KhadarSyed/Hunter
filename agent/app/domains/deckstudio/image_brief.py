"""What a slide's photo should show: the brands on the slide, the project's products and category, and the slide's
subject with analysis jargon removed. Queries go from most specific (brand + product) to most general (category)."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_QUERIES = 4
_WORD = re.compile(r"[A-Za-z][A-Za-z'&-]+")
JARGON = frozenset("""coverage share voice editorial earned media analysis overview top key trend trends over time
sentiment split themes theme cluster clusters outlets outlet ranking volume named mentions mention most cited
led citations affiliation affiliated across among featured associated centered with in of the and for on to by
question questions research brief takeaways summary objectives scope methodology sources thank you""".split())


@dataclass(frozen=True)
class Subjects:
    brands: list[str]
    products: list[str]
    category: str
    scene: str


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text or "") if w.lower() not in JARGON and len(w) > 2]


def subjects_for(slide, brands: list[str], products: list[str], category: str, scene: str = "") -> Subjects:
    on_slide = {c for ch in slide.charts for c in ch.get("categories", [])} | set(slide.logos)
    named = [b for b in brands if b in on_slide]
    topic = " ".join(dict.fromkeys(_words(f"{slide.kicker} {slide.title}")))[:60]
    return Subjects(brands=named, products=list(products), category=category, scene=scene or topic)


def queries(s: Subjects) -> list[str]:
    product = s.products[0] if s.products else s.category
    out = [f"{b} {product}" for b in s.brands[:2]]
    if s.scene:
        out.append(f"{s.category} {s.scene}" if s.category.split()[0].lower() not in s.scene.lower() else s.scene)
    out += [f"{s.category} {p}" for p in s.products[:1]] + [s.category]
    clean = []
    for q in out:
        q = " ".join(w for w in q.split() if w.lower() not in JARGON)
        if q and q.lower() not in {c.lower() for c in clean}:
            clean.append(q)
    return clean[:MAX_QUERIES]


def text_relevant(text: str, s: Subjects) -> bool:
    have = {w.lower() for w in _WORD.findall(text or "")}
    want = {w.lower() for term in (*s.brands, *s.products, s.category) for w in _WORD.findall(term) if len(w) > 3}
    return bool(have & want)


_SCENE_PROMPT = ("For each slide below, write one concrete photo scene (at most 8 words) that shows the slide's subject "
                 "for this category, brands and products: people, products, places. No charts, no text, no logos. "
                 'Reply as JSON {"<slide id>": "<scene>"}.')
SCENE_WORDS = 8


def scenes(llm, slides, brands: list[str], products: list[str], category: str) -> dict[str, str]:
    """One batched model call for every photo slide's scene; a scene that names none of the subjects is dropped."""
    if llm is None or not getattr(llm, "is_reachable", lambda: False)() or not slides:
        return {}
    listing = "\n".join(f"- {s.id}: {s.kicker} / {s.question or s.title}" for s in slides)
    context = f"Category: {category}. Brands: {', '.join(brands) or 'none'}. Products: {', '.join(products) or 'none'}."
    try:
        import json
        reply = json.loads(llm.chat([{"role": "system", "content": _SCENE_PROMPT},
                                     {"role": "user", "content": f"{context}\n{listing}"}], format_json=True) or "{}")
    except Exception:       # the deterministic topic is used instead
        return {}
    subject = Subjects(brands=brands, products=products, category=category, scene="")
    return {sid: " ".join(str(text).split()[:SCENE_WORDS]) for sid, text in reply.items()
            if isinstance(text, str) and text_relevant(text, subject)}
