"""Deterministic coverage metrics. No LLM, no guessing."""
from __future__ import annotations

from collections import Counter
from datetime import date


TOP_PEAKS = 5


def month_label(month: str) -> str:
    y, m = month.split("-")
    return date(int(y), int(m), 1).strftime("%b-%y")


def _top(counter: Counter, key: str, n: int = 10) -> list[dict]:
    return [{key: k, "count": c} for k, c in counter.most_common(n)]


