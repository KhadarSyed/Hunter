"""Client-brief upload: every supported format yields the full brief text.

Fixtures in fixtures/briefs/ are the Heineken client brief in PDF, DOCX, PPTX and XLSX,
styled like the client's document. Offline tests use native extraction; the live NVIDIA
Nemotron-Parse test runs only with LIVE_NVIDIA=1 (it calls NVIDIA's hosted API).
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from agent.app.core.nvidia_parse_client import clean_markdown  # noqa: E402
from agent.app.domains.brief import parser  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "briefs"
FORMATS = ["pdf", "docx", "pptx", "xlsx"]
BRIEF_ITEMS = [
    "Research questions",
    "Heineken Brand Perception and Relevance",
    "Black and Hispanic Millennials",
    "General conversation themes",
    "Positive and Negative Segment",
    "Brand associations",
    "premium, quality and aspiration",
]
BS = chr(92)  # backslash, spelled out so the LaTeX samples below stay readable


def _missing(text: str) -> list[str]:
    return [item for item in BRIEF_ITEMS if item.lower() not in text.lower()]


@pytest.mark.parametrize("fmt", FORMATS)
def test_native_extraction_finds_whole_brief(fmt, monkeypatch):
    monkeypatch.setenv("BRIEF_EXTRACTION_MODE", "native")
    result = parser.extract_brief_text(FIXTURES / f"heineken_brief.{fmt}")
    assert result["method"] == "native"
    assert _missing(result["text"]) == []


def test_unsupported_legacy_format_without_nvidia_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIEF_EXTRACTION_MODE", "native")
    legacy = tmp_path / "brief.doc"
    legacy.write_bytes(b"not really a doc")
    with pytest.raises(ValueError):
        parser.extract_brief_text(legacy)


def test_clean_markdown_normalises_nvidia_artifacts():
    raw = (
        f"# Research questions:\n\n{BS}({BS}bullet{BS}) Brand associations\n"
        f"{BS}({BS}cdot{BS}) Positive and Negative Segment\n{BS}- General conversation themes\n"
        f"Quality {BS}& aspiration<br>Premium<tbc>"
    )
    cleaned = clean_markdown(raw)
    assert "• Brand associations" in cleaned
    assert "• Positive and Negative Segment" in cleaned
    assert "• General conversation themes" in cleaned
    assert "Quality & aspiration\nPremium" in cleaned
    assert BS not in cleaned and "<" not in cleaned


@pytest.mark.skipif(os.getenv("LIVE_NVIDIA") != "1", reason="calls NVIDIA's hosted API; set LIVE_NVIDIA=1")
@pytest.mark.parametrize("fmt", FORMATS)
def test_nvidia_extraction_finds_whole_brief(fmt, monkeypatch):
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")  # NVIDIA key lives in .env
    monkeypatch.setenv("BRIEF_EXTRACTION_MODE", "nvidia")
    result = parser.extract_brief_text(FIXTURES / f"heineken_brief.{fmt}")
    assert result["method"] == "nvidia"
    assert _missing(result["text"]) == []
