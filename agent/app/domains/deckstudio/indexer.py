"""Learns slide types, deck families and design rules from whatever decks are in the reference folder.
Only geometry and style are reused; slide text is kept solely to detect copying (shingles)."""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from ...core import config, store

logger = logging.getLogger(__name__)
MAX_DECK_MB = 50
SHINGLE = 6
SLIDE_TYPES = ("cover", "contents", "objectives", "divider", "kpi_dashboard", "sov_doughnut_trend", "bar_with_cards",
               "trend_with_peaks", "sentiment_split", "theme_cards", "verbatim_wall", "person_cards",
               "comparison_table", "takeaways", "appendix_list", "closing", "other")
FAMILY_WORDS = {"audit": ("audit", "c-suite", "csuite"), "travel": ("travel", "7cs", "destination", "hotel", "bahamas"),
                "brand_social": ("social",), "topic_map": ("topic map",)}
_BIG_NUMBER = re.compile(r"^\s*\d{1,3}(?:[.,]\d+)?%?\s*$")
_WORD = re.compile(r"[a-z0-9']+")


def _chart_kind(chart) -> str:
    name = str(chart.chart_type).lower()
    return next((k for k in ("doughnut", "pie", "line", "bar", "column", "area") if k in name), "other")


def slide_features(slide, slide_w: int, slide_h: int) -> dict:
    texts, kinds, fonts, fills = [], [], Counter(), Counter()
    n_tables = n_pictures = big_numbers = 0
    cover = 0.0
    for sh in slide.shapes:
        if getattr(sh, "has_chart", False) and sh.has_chart:
            kinds.append(_chart_kind(sh.chart))
        if getattr(sh, "has_table", False) and sh.has_table:
            n_tables += 1
        if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
            n_pictures += 1
            if sh.width and sh.height and slide_w and slide_h:
                cover = max(cover, (sh.width * sh.height) / (slide_w * slide_h))
        if sh.has_text_frame and sh.text_frame.text.strip():
            texts.append(sh.text_frame.text)
            big_numbers += bool(_BIG_NUMBER.match(sh.text_frame.text))
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.font.name:
                        fonts[r.font.name] += 1
        try:
            if sh.fill.type == 1:
                fills[str(sh.fill.fore_color.rgb)] += 1
        except (AttributeError, TypeError, ValueError, NotImplementedError):
            pass
    text = "\n".join(texts)
    return {"words": len(_WORD.findall(text.lower())), "text": text[:4000], "chart_kinds": kinds, "n_charts": len(kinds),
            "n_tables": n_tables, "n_pictures": n_pictures, "picture_cover": round(cover, 3), "big_numbers": big_numbers,
            "fonts": [f for f, _ in fonts.most_common(3)], "fills": [f for f, _ in fills.most_common(5)]}


def classify(f: dict, index: int, n_slides: int) -> str:
    low, kinds = f["text"].lower(), set(f["chart_kinds"])
    if index == 0:
        return "cover"
    if index == n_slides - 1 and f["words"] < 60:
        return "closing"
    if re.search(r"table of contents|agenda|\bcontents\b", low):
        return "contents"
    if re.search(r"objective|scope", low) and not kinds:
        return "objectives"
    if f["picture_cover"] > 0.8 and f["words"] < 25:
        return "divider"
    if {"doughnut", "pie"} & kinds and "line" in kinds:
        return "sov_doughnut_trend"
    if f["big_numbers"] >= 3:
        return "kpi_dashboard"
    if f["n_tables"]:
        return "comparison_table"
    if "line" in kinds:
        return "trend_with_peaks"
    if {"doughnut", "pie"} & kinds:
        return "sentiment_split" if ("sentiment" in low or "positive" in low) else "kpi_dashboard"
    if {"bar", "column"} & kinds:
        return "bar_with_cards"
    if f["n_pictures"] >= 6:
        return "verbatim_wall"
    if f["n_pictures"] >= 3 and re.search(r"journalist|influencer|ceo|founder|reporter", low):
        return "person_cards"
    if re.search(r"takeaway|recommend|implication|so what", low):
        return "takeaways"
    if low.count("http") >= 4:
        return "appendix_list"
    return "theme_cards" if f["words"] > 60 else "other"


def deck_family(name: str, slides: list[dict]) -> str:
    low = name.lower()
    for family in ("audit", "travel"):
        if any(w in low for w in FAMILY_WORDS[family]):
            return family
    if ("verbatim" in low or "follow" in low or "additional" in low) and len(slides) <= 8:
        return "follow_up"
    if "social" in low and len(slides) > 20:
        return "brand_social"
    return "topic_map"


def _digest(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def index_library(folder: Path | None = None, progress=None) -> dict:
    """Indexes new or changed decks, skips locks/huge/broken files and drops decks that were removed."""
    folder = Path(folder or config.TEMPLATES_DIR)
    result = {"indexed": 0, "unchanged": 0, "skipped": 0, "removed": 0}
    paths = sorted(folder.glob("*.pptx")) if folder.exists() else []
    for i, path in enumerate(paths, start=1):
        if progress:
            progress(i, len(paths), path.stem)
        if path.name.startswith("~$") or path.stat().st_size > MAX_DECK_MB * 1024 * 1024:
            result["skipped"] += 1
            continue
        digest = _digest(path)
        known = store.get_library_deck(str(path))
        if known and known["hash"] == digest:
            result["unchanged"] += 1
            continue
        try:
            prs = Presentation(str(path))
            feats = [slide_features(s, prs.slide_width, prs.slide_height) for s in prs.slides]
        except Exception as e:      # a broken deck must not stop the library
            logger.warning("reference deck %s skipped: %s", path.name, type(e).__name__)
            result["skipped"] += 1
            continue
        slides = [{"n": n, "type": classify(f, n - 1, len(feats)), "features": f} for n, f in enumerate(feats, start=1)]
        deck_id = store.upsert_library_deck(str(path), digest, deck_family(path.name, slides), len(slides))
        store.replace_library_slides(deck_id, slides)
        result["indexed"] += 1
    for deck in store.list_library_decks():
        if deck["path"].startswith(str(folder)) and not Path(deck["path"]).exists():
            store.delete_library_deck(deck["path"])
            result["removed"] += 1
    return result


def design_rules(family: str) -> dict:
    slides = [s for s in store.list_library_slides() if s["family"] == family] or store.list_library_slides()
    fonts = [f for f, _ in Counter(f for s in slides for f in s["features"].get("fonts", [])).most_common(4)]
    fills = Counter(c for s in slides for c in s["features"].get("fills", []))
    return {"title_font": fonts[0] if fonts else "Georgia", "body_font": fonts[1] if len(fonts) > 1 else "Arial",
            "fills": [c for c, _ in fills.most_common(8)], "slide_types": dict(Counter(s["type"] for s in slides))}


def reference_text_shingles() -> set[tuple[str, ...]]:
    out = set()
    for s in store.list_library_slides():
        words = _WORD.findall(s["features"].get("text", "").lower())
        out.update(tuple(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1))
    return out
