"""One display label per category, whatever spelling the data or the tagger used: 'Cut' / 'cuts', 'Blisters' /
'blisters', 'Band-Aid' / 'band aid' / 'bandaid' are counted as one bar, never split across several."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


def canon(text: str) -> str:
    """The key variants share: case, spacing, punctuation and a plural 's' ignored ('Band-Aids' -> 'bandaid')."""
    key = _NOT_ALNUM.sub("", str(text).lower())
    return key[:-1] if len(key) > 3 and key.endswith("s") and not key.endswith("ss") else key


def unify(values: Iterable[str], preferred: Iterable[str] = ()) -> dict[str, str]:
    """{raw value: its group's display label}. A preferred spelling (a question's own value names) wins, else the
    group's most frequent spelling, capitalised forms first on a tie."""
    counts = Counter(str(v) for v in values if str(v).strip())
    groups: dict[str, Counter] = {}
    for value, n in counts.items():
        groups.setdefault(canon(value), Counter())[value] += n
    named = {canon(p): str(p) for p in preferred}
    out: dict[str, str] = {}
    for key, forms in groups.items():
        label = named.get(key) or max(forms, key=lambda v: (forms[v], v[:1].isupper(), -len(v)))
        out.update({form: label for form in forms})
    return out
