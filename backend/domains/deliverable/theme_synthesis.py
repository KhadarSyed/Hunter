"""Thematic analysis of a question's articles: the tagger's per-article themes consolidated into distinct,
client-ready themes. GPT only groups the labels and titles each group; every count and rank is computed from the
articles themselves, so no frequency is invented.

Guardrails (the analyst brief): rank by actual mention frequency; merge subthemes that are the same underlying
subject; keep materially different issues apart; never split a major theme to add findings or lift a minor one for
being interesting; titles are precise, professional report headings with varied structure."""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import replace

from .engine_types import EngineRow
from .labels import canon, theme_key

logger = logging.getLogger(__name__)

MAX_THEMES = 80          # labels sent in one call, most frequent first; the long tail keeps its own wording
SAMPLE_TITLES = 2        # article titles shown per label so GPT judges substance, not just wording

_RULES = """You are a senior media-research analyst consolidating article themes for a client presentation.
Each input label is a theme the tagger gave individual articles, with how many articles carry it and sample headlines.

Group the labels into themes:
- Merge labels that describe the same underlying subject or development, including closely related subthemes.
- Keep labels apart when they reflect materially different issues, perspectives or developments.
- Do not create overlapping themes that communicate essentially the same finding.
- Do not split a major subject into smaller themes to increase the number of findings.
- Do not merge an unrelated minor label into a major theme to inflate it; leave it as its own theme.
- Every input label belongs to exactly one theme. Use the labels exactly as given.

Title each theme:
- A professional, descriptive, precise research-report heading that states the central subject (3-9 words).
- Use business, industry and research terminology where it fits; reflect what the articles actually discuss.
- No generic, vague, conversational, sensational or speculative wording; no question marks or exclamation marks.
- Each title distinct; do not reuse the same sentence structure across titles.
- Do not put counts, rankings or percentages in titles.

Return JSON {"themes": [{"title": "...", "labels": ["input label", ...]}]}."""


def _label_stats(rows: list[EngineRow]) -> tuple[Counter, dict[str, str], dict[str, list[str]]]:
    counts: Counter = Counter()
    display: dict[str, str] = {}
    samples: dict[str, list[str]] = {}
    for r in rows:
        for key in {theme_key(t) for t in r.themes if t and t.strip()}:
            counts[key] += 1
            titles = samples.setdefault(key, [])
            if len(titles) < SAMPLE_TITLES and r.article.title:
                titles.append(r.article.title[:140])
        for t in r.themes:
            if t and t.strip():
                display.setdefault(theme_key(t), t.strip())
    return counts, display, samples


def _ask(llm, question: str, labels: list[dict]) -> list[dict]:
    prompt = f"{_RULES}\n\nRESEARCH QUESTION: {question}\nLABELS: {json.dumps(labels, ensure_ascii=False)}"
    try:
        reply = json.loads(llm.chat([{"role": "user", "content": prompt}], format_json=True))
    except Exception as e:      # the tagger's own labels stand: unconsolidated beats a wrong merge
        logger.warning("theme consolidation unavailable: %s", type(e).__name__)
        return []
    return (reply.get("themes") or []) if isinstance(reply, dict) else []


def title_map(groups: list[dict], display: dict[str, str]) -> dict[str, str]:
    """{theme_key of an input label: its theme's title}. A label GPT did not return or invented keeps its own
    wording, a label placed twice keeps its first theme, and two themes with the same title are one theme."""
    titles: dict[str, str] = {}               # canon(title) -> first spelling, so duplicate titles merge
    out: dict[str, str] = {}
    for g in groups:
        title = " ".join(str(g.get("title") or "").split()).strip(" .")
        if not title or not isinstance(g.get("labels"), list):
            continue
        title = titles.setdefault(canon(title), title)
        for label in g["labels"]:
            key = theme_key(str(label))
            if key in display and key not in out:
                out[key] = title
    return out


def consolidate(llm, question: str, rows: list[EngineRow], log=None) -> list[EngineRow]:
    """The question's rows with each article's themes replaced by its consolidated theme titles (an article is
    counted once per theme even when two of its labels merged). Rows are copied, never changed in place."""
    counts, display, samples = _label_stats(rows)
    if llm is None or len(counts) < 2:
        return rows
    labels = [{"label": display[k], "articles": c, "sample_headlines": samples.get(k, [])}
              for k, c in counts.most_common(MAX_THEMES)]
    mapping = title_map(_ask(llm, question, labels), display)
    if not mapping:
        return rows
    if log:
        log(f"Themes consolidated: {len(counts)} tagged labels into {len(set(mapping.values()))} themes")
    return [replace(r, themes=list(dict.fromkeys(mapping.get(theme_key(t), t.strip())
                                                 for t in r.themes if t and t.strip())))
            for r in rows]
