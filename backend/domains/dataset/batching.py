"""Batches sized to the model, not to a fixed count: articles are added while the prompt stays under the input
budget and the expected reply under the output budget (GPT-5 defaults; override in .env)."""
from __future__ import annotations

import os
from collections.abc import Callable

CHARS_PER_TOKEN = 4
INPUT_BUDGET = int(os.getenv("HUNTER_TAG_INPUT_TOKENS", "100000"))     # ~40% of GPT-5's 272k input window
OUTPUT_BUDGET = int(os.getenv("HUNTER_TAG_OUTPUT_TOKENS", "12000"))    # under the client's 16,384 output cap
MAX_ARTICLE_CHARS = int(os.getenv("HUNTER_TAG_ARTICLE_CHARS", "8000"))  # one long piece never fills a batch


def tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


def trim(text: str, max_chars: int = MAX_ARTICLE_CHARS) -> str:
    return text if len(text) <= max_chars else text[:max_chars].rsplit(" ", 1)[0] + " …"


def pack(items: list[dict], text_of: Callable[[dict], str], *, out_per_item: int,
         input_budget: int | None = None, output_budget: int | None = None) -> list[list[dict]]:
    cap_in, cap_out = input_budget or INPUT_BUDGET, output_budget or OUTPUT_BUDGET
    batches: list[list[dict]] = []
    cur: list[dict] = []
    used_in = 0
    for item in items:
        need = tokens(text_of(item))
        if cur and (used_in + need > cap_in or (len(cur) + 1) * out_per_item > cap_out):
            batches.append(cur)
            cur, used_in = [], 0
        cur.append(item)
        used_in += need
    if cur:
        batches.append(cur)
    return batches
