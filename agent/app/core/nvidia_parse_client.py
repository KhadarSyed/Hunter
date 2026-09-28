"""NVIDIA Nemotron-Parse client — document → text extraction via NVIDIA's hosted NIM.

Nemotron-Parse reads page *images* and returns layout-aware Markdown (headings, lists,
tables). Every supported upload is therefore turned into page images first:

    PDF                    → rendered page-by-page with PyMuPDF
    DOCX/DOC, PPTX/PPT,    → converted to PDF (LibreOffice if installed, else Microsoft
    XLSX/XLS                 Office via COM on Windows), then rendered

API (verified live against integrate.api.nvidia.com, 2026-09):
    POST {NVIDIA_PARSE_API_URL}/chat/completions
    messages: one user message whose content is a single `image_url` part (no text part —
              the model rejects text input), plus
    tools/tool_choice: the `markdown_no_bbox` function
    → choices[0].message.tool_calls[0].function.arguments = JSON list of {"text": ...}
`nvidia/nemotron-parse-2.0` is listed in the catalog but its hosted endpoint returned
500/502 and rejects tool calls at the time of writing, so v1 is the default.

Config (env): NVIDIA_PARSE_API_KEY (falls back to NVIDIA_EMBED_API_KEY — one
build.nvidia.com key covers both), NVIDIA_PARSE_API_URL, NVIDIA_PARSE_MODEL.
The API key is a secret: never log or return it.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "nvidia/nemotron-parse"
DEFAULT_API_URL = "https://integrate.api.nvidia.com/v1"
PARSE_TOOL = "markdown_no_bbox"
MAX_PAGES = 20            # briefs are short; caps cost/latency for accidental large uploads
PDF_RENDER_ZOOM = 2.0     # ~144 dpi — enough for small print without huge payloads
REQUEST_TIMEOUT_S = 90
CONVERT_TIMEOUT_S = 120

OFFICE_EXTENSIONS = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"}
SUPPORTED_EXTENSIONS = {".pdf"} | OFFICE_EXTENSIONS


class NvidiaParseError(RuntimeError):
    pass


# Nemotron-Parse emits some symbols as LaTeX / Markdown escapes; normalise them to plain
# text so the brief shown to the analyst (and sent to the Brief & Scope LLM) is clean.
_CLEANUPS = [
    (re.compile(r"\\\(\s*\\(?:bullet|cdot|circ|star|ast|diamond)\s*\\\)"), "•"),  # \(\bullet\) -> •
    (re.compile(r"^\\[-*+]\s*", re.MULTILINE), "• "),                          # line-leading \- -> •
    (re.compile(r"\\([&%$#_{}~^])"), r"\1"),                                    # \& -> &
    (re.compile(r"\s*<br\s*/?>\s*", re.IGNORECASE), "\n"),                      # <br> -> newline
    (re.compile(r"</?(?:tbc|tbd|sup|sub|u)>", re.IGNORECASE), ""),              # stray layout tags
]


def clean_markdown(text: str) -> str:
    for pattern, repl in _CLEANUPS:
        text = pattern.sub(repl, text)
    return text.replace("’", "'").strip()


# ─── Office → PDF conversion ─────────────────────────────────────────────────

_office_lock = threading.Lock()  # Office COM automation is not safe to drive concurrently


def _find_soffice() -> str | None:
    for candidate in (shutil.which("soffice"), shutil.which("libreoffice"),
                      r"C:\Program Files\LibreOffice\program\soffice.exe",
                      r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _convert_with_libreoffice(soffice: str, src: Path, out_dir: Path) -> Path:
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
                   check=True, capture_output=True, timeout=CONVERT_TIMEOUT_S)
    pdf = out_dir / (src.stem + ".pdf")
    if not pdf.exists():
        raise NvidiaParseError("LibreOffice produced no PDF")
    return pdf


def _convert_with_ms_office(src: Path, pdf: Path) -> Path:
    import pythoncom
    import win32com.client

    ext = src.suffix.lower()
    pythoncom.CoInitialize()
    app = None
    try:
        if ext in (".docx", ".doc"):
            app = win32com.client.DispatchEx("Word.Application")
            doc = app.Documents.Open(str(src), ReadOnly=True)
            doc.ExportAsFixedFormat(str(pdf), 17)  # wdExportFormatPDF
            doc.Close(False)
        elif ext in (".pptx", ".ppt"):
            app = win32com.client.DispatchEx("PowerPoint.Application")
            pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
            pres.SaveAs(str(pdf), 32)  # ppSaveAsPDF
            pres.Close()
        else:  # .xlsx / .xls
            app = win32com.client.DispatchEx("Excel.Application")
            app.DisplayAlerts = False
            wb = app.Workbooks.Open(str(src), ReadOnly=True)
            wb.ExportAsFixedFormat(0, str(pdf))  # xlTypePDF, all sheets
            wb.Close(False)
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:  # already gone
                pass
        pythoncom.CoUninitialize()
    if not pdf.exists():
        raise NvidiaParseError("Microsoft Office produced no PDF")
    return pdf


def to_pdf(file_bytes: bytes, filename: str) -> bytes:
    """Convert an Office document to PDF bytes (LibreOffice, else MS Office on Windows)."""
    ext = Path(filename).suffix.lower()
    if ext not in OFFICE_EXTENSIONS:
        raise NvidiaParseError(f"Cannot convert {ext or 'this file type'} to PDF")
    with tempfile.TemporaryDirectory(prefix="hunter_parse_") as tmp:
        src = Path(tmp) / f"input{ext}"
        src.write_bytes(file_bytes)
        soffice = _find_soffice()
        try:
            with _office_lock:
                if soffice:
                    pdf = _convert_with_libreoffice(soffice, src, Path(tmp))
                elif sys.platform == "win32":
                    pdf = _convert_with_ms_office(src, Path(tmp) / "output.pdf")
                else:
                    raise NvidiaParseError("No document converter: install LibreOffice to parse Office files")
        except NvidiaParseError:
            raise
        except Exception as e:  # converter crashed / timed out / Office missing
            raise NvidiaParseError(f"Could not convert {ext} to PDF: {e}") from e
        return pdf.read_bytes()


# ─── NVIDIA client ───────────────────────────────────────────────────────────

class NvidiaParseClient:
    def __init__(self, api_key: str | None = None, api_url: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("NVIDIA_PARSE_API_KEY", "") or os.getenv("NVIDIA_EMBED_API_KEY", "")
        self.api_url = (api_url or os.getenv("NVIDIA_PARSE_API_URL", "") or DEFAULT_API_URL).rstrip("/")
        self.model = model or os.getenv("NVIDIA_PARSE_MODEL", "") or DEFAULT_MODEL

    def is_reachable(self) -> bool:
        return bool(self.api_key and self.api_url and self.model)

    def _parse_image(self, png_b64: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
            ]}],
            "tools": [{"type": "function", "function": {"name": PARSE_TOOL}}],
            "tool_choice": {"type": "function", "function": {"name": PARSE_TOOL}},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        try:
            r = requests.post(f"{self.api_url}/chat/completions", headers=headers, json=payload,
                              timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as e:
            raise NvidiaParseError(f"NVIDIA parse request failed: {e}") from e
        if r.status_code != 200:
            raise NvidiaParseError(f"NVIDIA parse failed: {r.status_code} {r.text[:200]}")
        try:
            message = r.json()["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if not calls:
                return message.get("content") or ""
            blocks = json.loads(calls[0]["function"]["arguments"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise NvidiaParseError(f"Unexpected NVIDIA parse response: {e}") from e
        # arguments is a list of {"text": ...} blocks (possibly nested one level per page)
        flat = [b for item in blocks for b in (item if isinstance(item, list) else [item])]
        return "\n\n".join(b.get("text", "").strip() for b in flat if isinstance(b, dict) and b.get("text"))

    def parse_pdf(self, pdf_bytes: bytes) -> tuple[str, int]:
        """Return (markdown text, pages parsed)."""
        import pymupdf

        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            raise NvidiaParseError(f"Could not open PDF: {e}") from e
        pages: list[str] = []
        try:
            count = min(len(doc), MAX_PAGES)
            matrix = pymupdf.Matrix(PDF_RENDER_ZOOM, PDF_RENDER_ZOOM)
            for i in range(count):
                png = base64.b64encode(doc[i].get_pixmap(matrix=matrix).tobytes("png")).decode("ascii")
                text = self._parse_image(png).strip()
                if text:
                    pages.append(text)
        finally:
            doc.close()
        return clean_markdown("\n\n".join(pages)), count

    def parse_document(self, file_bytes: bytes, filename: str) -> tuple[str, int]:
        """Extract Markdown text from a PDF or Office document. Raises NvidiaParseError."""
        if not self.is_reachable():
            raise NvidiaParseError("NVIDIA parse not configured (NVIDIA_PARSE_API_KEY / NVIDIA_EMBED_API_KEY)")
        ext = Path(filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise NvidiaParseError(f"NVIDIA parse does not support {ext or 'this file type'}")
        pdf = file_bytes if ext == ".pdf" else to_pdf(file_bytes, filename)
        return self.parse_pdf(pdf)


_default_client: NvidiaParseClient | None = None


def _client() -> NvidiaParseClient:
    global _default_client
    if _default_client is None:
        _default_client = NvidiaParseClient()
    return _default_client


def parse_document(file_bytes: bytes, filename: str) -> tuple[str, int]:
    return _client().parse_document(file_bytes, filename)


def is_reachable() -> bool:
    return _client().is_reachable()


def model_name() -> str:
    return _client().model
