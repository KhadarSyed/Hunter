"""NVIDIA Nemotron-Parse OCR/document-parsing client — fallback for scanned uploads.

Talks to NVIDIA's hosted NIM chat-completions-compatible endpoint for Nemotron-Parse,
configured from: NVIDIA_PARSE_API_KEY, NVIDIA_PARSE_API_URL, NVIDIA_PARSE_MODEL.
Sibling of nvidia_embed_client.py (same location, same env-var/class/error/is_reachable pattern).

BEST-EFFORT / UNVERIFIED NOTE (2026-09, plan chunk "3. OCR fallback for file upload"):
This session confirmed via NVIDIA's public docs (docs.nvidia.com/nim/vision-language-models,
"Query the Nemotron-Parse-v1.2 API" page, fetched directly this session) that the NIM container
exposes an OpenAI-compatible `POST /v1/chat/completions` endpoint. The request is a normal chat
message whose `content` is a list mixing a `text` part carrying special control tokens
(`<output_markdown>`, `<predict_bbox>`, `<predict_classes>`, `<predict_no_text_in_pic>`) with an
`image_url` part (a public URL or a base64 `data:image/...;base64,...` URI). The response is the
standard OpenAI shape: `choices[0].message.content` holds the extracted markdown text.

That page's worked example targets a *self-hosted* NIM container (`http://0.0.0.0:8000/v1`), not
the hosted `build.nvidia.com` / `integrate.api.nvidia.com` catalog endpoint this client actually
calls (matching this codebase's existing `NVIDIA_EMBED_API_URL` default). Separately-found public
examples of hosted-NIM calls (e.g. for other Nemotron models) use `Authorization: Bearer nvapi-...`
against the same `{base}/chat/completions` path, so this client assumes the hosted endpoint mirrors
the self-hosted request/response shape — that assumption is NOT independently confirmed for
Nemotron-Parse specifically and should be validated against a real account before relying on it.
The exact catalog model slug is also unconfirmed: NVIDIA's docs/catalog referenced
`nvidia/nemotron-parse-v1.2`, `nvidia/nemotron-parse-2.0`, and an unversioned `nvidia/nemotron-parse`
in different places found during research. `NVIDIA_PARSE_MODEL` below defaults to the unversioned
slug (the common "always latest" hosted-catalog convention) — override via env once verified.

Nemotron-Parse operates on IMAGES, not raw document bytes. Given that, this client only actually
performs OCR for PDFs: each page is rasterized to a PNG via PyMuPDF/fitz (already a project
dependency, see agent/requirements.txt) and sent as a base64 image. PPTX/DOCX are still accepted as
trigger extensions at the call site (agent/app/domains/brief/router.py) per the task spec, but
`parse_document()` raises `NvidiaParseError` for them immediately: rendering PPTX/DOCX pages to
images would need a heavy new dependency (e.g. a LibreOffice headless conversion step) that is out
of scope for this surgical chunk. Scanned/image-only uploads are overwhelmingly PDFs in practice, so
this covers the real-world case; DOCX/PPTX still degrade gracefully (caller falls back to whatever
text was already extracted, ocr_used stays False) rather than erroring out.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# Cost/latency guard, not a correctness limit — a NIM call per page adds up fast on a large scan.
MAX_OCR_PAGES = 10
# Rasterization zoom factor (2.0 ~= 144 DPI from a 72-DPI PDF page) — enough for OCR accuracy
# without producing huge base64 payloads. Tune with real scanned-PDF usage.
PDF_RENDER_ZOOM = 2.0


class NvidiaParseError(RuntimeError):
    pass


class NvidiaParseClient:
    def __init__(self, api_key: str | None = None, api_url: str | None = None, model: str | None = None):
        # NVIDIA_PARSE_API_KEY falls back to NVIDIA_EMBED_API_KEY when unset: both are NVIDIA NIM
        # models that plausibly share one build.nvidia.com account/API key in this deployment
        # (there is no dedicated parse key configured yet). Set NVIDIA_PARSE_API_KEY explicitly to
        # override once/if a separate key is issued.
        self.api_key = (
            api_key
            or os.getenv("NVIDIA_PARSE_API_KEY", "")
            or os.getenv("NVIDIA_EMBED_API_KEY", "")
        )
        self.api_url = (
            api_url or os.getenv("NVIDIA_PARSE_API_URL", "https://integrate.api.nvidia.com/v1")
        ).rstrip("/")
        self.model = model or os.getenv("NVIDIA_PARSE_MODEL", "nvidia/nemotron-parse")

    def is_reachable(self) -> bool:
        return bool(self.api_key and self.api_url and self.model)

    def _call_nim(self, image_b64: str, image_format: str = "png") -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "<output_markdown><predict_no_text_in_pic>"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{image_format};base64,{image_b64}"},
                        },
                    ],
                }
            ],
            "temperature": 0.0,
        }
        r = requests.post(f"{self.api_url}/chat/completions", headers=headers, json=payload, timeout=90)
        if r.status_code != 200:
            raise NvidiaParseError(f"NVIDIA parse/OCR failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise NvidiaParseError(f"NVIDIA parse/OCR returned unexpected response shape: {e}") from e

    def _parse_pdf(self, file_bytes: bytes) -> str:
        try:
            import fitz  # PyMuPDF — already a dependency, see agent/requirements.txt
        except ImportError as e:
            raise NvidiaParseError("PyMuPDF not available for OCR page rasterization") from e

        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as e:
            raise NvidiaParseError(f"Could not open PDF for OCR rasterization: {e}") from e

        pages_text: list[str] = []
        try:
            page_count = min(len(doc), MAX_OCR_PAGES)
            matrix = fitz.Matrix(PDF_RENDER_ZOOM, PDF_RENDER_ZOOM)
            for i in range(page_count):
                pix = doc[i].get_pixmap(matrix=matrix)
                image_b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
                page_text = self._call_nim(image_b64, "png")
                if page_text.strip():
                    pages_text.append(page_text.strip())
        finally:
            doc.close()
        return "\n\n".join(pages_text)

    def parse_document(self, file_bytes: bytes, filename: str) -> str:
        """Extract text from a likely-scanned document via NVIDIA's OCR/parse NIM.

        Only PDF is actually wired up today (see module docstring for why). Raises
        NvidiaParseError on any failure — callers must catch it and fall back to whatever text was
        already extracted; this must never propagate as an unhandled 500.
        """
        if not self.is_reachable():
            raise NvidiaParseError("NVIDIA_PARSE_API_KEY/API_URL/MODEL not configured")

        ext = Path(filename or "").suffix.lower()
        if ext == ".pdf":
            return self._parse_pdf(file_bytes)
        raise NvidiaParseError(
            f"OCR fallback not implemented for {ext or 'this file type'} — "
            "Nemotron-Parse requires page images; only PDF rasterization is wired up"
        )


_default_client: NvidiaParseClient | None = None


def _get_default_client() -> NvidiaParseClient:
    global _default_client
    if _default_client is None:
        _default_client = NvidiaParseClient()
    return _default_client


def parse_document(file_bytes: bytes, filename: str) -> str:
    """Module-level convenience wrapper around a lazily-created default client."""
    return _get_default_client().parse_document(file_bytes, filename)


def is_reachable() -> bool:
    return _get_default_client().is_reachable()
