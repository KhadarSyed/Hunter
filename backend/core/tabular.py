"""Read CSV exports whatever their encoding and delimiter. Meltwater writes UTF-16 LE, tab-separated files;
Excel on Windows writes cp1252 comma-separated ones."""
from __future__ import annotations

import csv
import io
from pathlib import Path

_BOMS = ((b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"), (b"\xef\xbb\xbf", "utf-8-sig"))
_FALLBACKS = ("utf-8", "cp1252", "latin-1")
_DELIMITERS = ",\t;|"
_NUL_PROBE = 400
_EXTRA = "__extra__"


def decode_text(raw: bytes) -> str:
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace")
    probe = raw[:_NUL_PROBE]
    if probe and probe.count(b"\x00") > len(probe) // 4:      # UTF-16 without a BOM: every other byte is NUL
        return raw.decode("utf-16-le" if probe[1:2] == b"\x00" else "utf-16-be", errors="replace")
    for encoding in _FALLBACKS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sniff_delimiter(text: str) -> str:
    """The delimiter that splits the header line most, counted outside quotes."""
    header = next((line for line in text.lstrip("\ufeff").splitlines() if line.strip()), "")
    counts, quoted = {d: 0 for d in _DELIMITERS}, False
    for ch in header:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in counts:
            counts[ch] += 1
    best = max(_DELIMITERS, key=lambda d: counts[d])
    return best if counts[best] else ","


def read_csv_dicts(path: str | Path) -> list[dict[str, str]]:
    text = decode_text(Path(path).read_bytes()).lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=sniff_delimiter(text), restkey=_EXTRA)
    return [{k.strip(): (v or "") for k, v in raw.items() if isinstance(k, str) and k != _EXTRA and k.strip()}
            for raw in reader]
